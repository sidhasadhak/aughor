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

import hmac
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ConfigDict, Field

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

_client = AughorClient()


class PolicedFastMCP(FastMCP):
    """DE-2b (ROADMAP §3.51) — the server lists and runs only what the organisation's agent
    policy allows.

    The policy is the API's (`GET /org-settings/agent-policy`, read with this server's
    principal, cached thirty seconds); the API enforces it again on every call, so this is
    the courtesy, not the lock: a disallowed tool is HIDDEN from `tools/list` rather than
    offered and failed, and one called by name anyway is refused with the same stable code
    the API would give. Every tool carries the protocol's hints — `readOnlyHint` for a read,
    `destructiveHint` for an act — from the one level map (`mcp/policy.py`). When the API
    cannot be asked, the install's default (`run`) is applied, which is what the API will
    enforce anyway.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The tool list is LIVE (`refresh_live_tools`), so say so: `tools.listChanged`.
        low = self._mcp_server
        initial = low.create_initialization_options

        def _options(notification_options=None, experimental_capabilities=None):
            return initial(notification_options or NotificationOptions(tools_changed=True),
                           experimental_capabilities)

        low.create_initialization_options = _options

    async def list_tools(self):
        from aughor.mcp.policy import tool_annotations, tool_level
        await refresh_live_tools()
        policy = await current_policy()
        out = []
        for t in await super().list_tools():
            level = tool_level(t.name)
            if not (policy.allows_tool(t.name) and policy.allows_level(level)):
                continue
            out.append(t.model_copy(update={"annotations": tool_annotations(level)}))
        return out

    async def call_tool(self, name: str, arguments: dict):
        import json as _json

        from mcp.server.fastmcp.exceptions import ToolError

        from aughor.mcp.client import CURRENT_TOOL
        from aughor.mcp.policy import CODE_LEVEL, CODE_TOOL, refusal, tool_level
        policy = await current_policy()
        level = tool_level(name)
        if name in getattr(self._tool_manager, "_tools", {}):
            if not policy.allows_tool(name):
                raise ToolError(_json.dumps(refusal(CODE_TOOL, tool=name, policy_level=policy.level)))
            if not policy.allows_level(level):
                raise ToolError(_json.dumps(refusal(CODE_LEVEL, tool=name, policy_level=policy.level, required=level)))
        token = CURRENT_TOOL.set(name)
        try:
            return await super().call_tool(name, arguments)
        finally:
            CURRENT_TOOL.reset(token)
            if await refresh_live_tools():
                await self._say_the_list_changed()

    async def _say_the_list_changed(self) -> None:
        """`notifications/tools/list_changed` on the session this request came in on — a
        client re-lists and sees the agent or automation that appeared, without reconnecting."""
        try:
            await self.get_context().session.send_tool_list_changed()
        except Exception as exc:                  # no session (a direct call), or it closed
            _log.debug("could not send tools/list_changed: %s", exc)


_POLICY_TTL = 30.0
_policy_cache: list = []   # [(fetched_at, AgentPolicy)]


async def current_policy():
    """The effective agent policy for this server's principal, from the API; the default when
    the API cannot say (and that is logged once per fetch, not hidden)."""
    import time as _time

    from aughor.orgsettings.agent_policy import DEFAULT_POLICY, AgentPolicy
    if _policy_cache and (_time.monotonic() - _policy_cache[0][0]) < _POLICY_TTL:
        return _policy_cache[0][1]
    policy = DEFAULT_POLICY
    try:
        answer = await _client.agent_policy()
        eff = (answer or {}).get("effective") or {}
        policy = AgentPolicy(
            level=str(eff.get("level") or "run"),
            connections=tuple(eff["connections"]) if eff.get("connections") is not None else None,
            tools=tuple(eff["tools"]) if eff.get("tools") is not None else None,
            set_by=str(eff.get("set_by") or ""), source=str(eff.get("source") or "saved"),
        )
    except Exception as exc:
        _log.warning("could not read the agent policy from the API (%s); applying the default, `run`", exc)
    _policy_cache[:] = [(_time.monotonic(), policy)]
    return policy


def forget_policy() -> None:
    """Drop the cached policy, so the next list or call reads it again (tests, and a client
    that was just granted more)."""
    _policy_cache.clear()


mcp = PolicedFastMCP("Aughor", instructions=_INSTRUCTIONS)


@mcp.tool()
async def list_connections() -> list[dict]:
    """List the data warehouses/connections Aughor can analyze. CALL THIS FIRST — every
    other tool needs a `connection` id from here. Returns each connection's id, name,
    dialect, and (for multi-schema connections) its schema names."""
    return await _client.list_connections()


# ── Phase 7 of the 2027 study — the ledger API through the same door ───────────────────────

@mcp.tool()
async def read_contract() -> dict:
    """Read the agent contract Aughor holds every agent to — its own and yours: the seven duties
    and what each may book, the typed verdicts a run ends in, what an entry must carry (kinds,
    tiers, warrants and the laws at the ledger's door), who may book, the levels, the doors, how
    an agent is scored (by what became of its entries, never by a judge) and every refusal code.
    Read it once before posting a claim."""
    return await _client.contract()


@mcp.tool()
async def read_claims(
    connection: Annotated[Optional[str], Field(description="A connection id from list_connections; omit for organisation-wide claims too.")] = None,
    kind: Annotated[Optional[str], Field(description="observation · finding · reading · definition · hypothesis · prediction · said · cause")] = None,
    author: Annotated[Optional[str], Field(description="A principal, e.g. service:acme-forecaster, to read one author's entries.")] = None,
    as_of: Annotated[Optional[str], Field(description="An ISO date: each claim as it stood on that day (belief as a view).")] = None,
    limit: Annotated[int, Field(description="At most this many claims.")] = 50,
) -> list[dict]:
    """Read what the organisation holds true from Aughor's ledger: current claims, or — with
    `as_of` — each claim as it was recorded on that date. Every claim carries its warrant, its
    tier, its author and, where counted, how often claims of its class have been right (a hit rate
    with its n, or nothing — never a model's confidence)."""
    return await _client.read_claims(connection=connection, kind=kind, author=author, as_of=as_of, limit=limit)


@mcp.tool()
async def read_restatements(
    since: Annotated[str, Field(description="An ISO moment; every claim restated after it, oldest first. Empty for the recent ones.")] = "",
    connection: Annotated[Optional[str], Field(description="A connection id to narrow to.")] = None,
    limit: Annotated[int, Field(description="At most this many.")] = 100,
) -> dict:
    """What the ledger changed its mind about since a cursor: each restated claim with the text it
    replaced, and the cursor to read from next time. Poll this after relying on a number, or
    subscribe to `claim.restated` through the ledger API for a webhook."""
    return await _client.read_restatements(since=since, connection=connection, limit=limit)


@mcp.tool()
async def post_claim(
    kind: Annotated[str, Field(description="observation · finding · reading · hypothesis · prediction · said · cause (a definition is a person's).")],
    text: Annotated[str, Field(description="The statement, in words.")],
    warrants: Annotated[list[dict], Field(description="At least one: [{kind: run|document|attestation|claim, ref: <receipt id, document locator, verdict id or claim id>, detail?}].")],
    connection: Annotated[Optional[str], Field(description="The connection the claim is about; omit for an organisation-wide claim.")] = None,
    tier: Annotated[str, Field(description="said (default) · mined · measured (needs a run warrant); approved and declared are a person's.")] = "said",
    metric: Annotated[str, Field(description="The metric the statement is about, when one; required for a prediction.")] = "",
    value: Annotated[Optional[float], Field(description="The typed value, when one.")] = None,
    unit: Annotated[str, Field(description="The value's unit.")] = "",
    as_of: Annotated[str, Field(description="The data's date (ISO); today when empty.")] = "",
    natural_key: Annotated[str, Field(description="Your own key for this claim, to restate it later under the same key.")] = "",
    state: Annotated[str, Field(description="hypothesis: open · supported · refuted; prediction: open.")] = "",
) -> dict:
    """Post a claim into Aughor's ledger with its warrant, as yourself (your service principal is the
    author; every entry carries it and is scored by what becomes of it). The ledger's laws are
    enforced at the door: no fact without a warrant, no model-authored fact above tier `said`, no
    stated confidence. A refusal says why, with its code. Read `read_contract` first."""
    body = {"kind": kind, "statement": {"text": text, "metric": metric, "value": value, "unit": unit}, "tier": tier,
            "about": {"kind": "connection", "key": connection} if connection else {"kind": "organisation", "key": ""},
            "warrants": warrants, "as_of": as_of, "natural_key": natural_key, "state": state}
    return await _client.post_claim(body)


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
# Wave S6 read these four IN this process, "deliberately and against the module's general
# rule", to save a hop. DE-2c (ROADMAP §3.51) reversed that: in this process no principal is
# bound, so every read was the default organisation's, the clearance trim saw no caller and
# the connection-owner check never ran — the hop it saved was the governance. The bodies
# stay in `knowledge_tools.py` (the API's chat tools call them in-process too); these tools
# now reach them through `GET /knowledge/{connection}/…`, under the request's organisation,
# user and RBAC, like every other tool here.

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
    return await _client.search_graph(connection, query, limit=limit)


@mcp.tool()
async def describe_entity(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    entity: Annotated[str, Field(description="An object type or table name, e.g. 'shipment' or 'orders'.")],
) -> dict:
    """What one business object TYPE is — an order, a customer, a shipment — as Aughor's ontology
    measured it: its key and whether the data proves it unique, the property that names one, every
    property with its role, type and SOURCE (the table and column it is read from), its links to other
    types by name with measured cardinality and whether each can be followed (or why not), the declared
    actions that take it, and its verified metrics. The slice Aughor's entity-type map renders, so an
    agent and a person asking what a Shipment is get one answer. `kind` says where it came from: the
    ontology (`object_type`), or — where none is built — the knowledge graph's table node (`table`).
    `available=false` with a `notice` means it exists but is withheld by data governance."""
    return await _client.describe_entity(connection, entity)


@mcp.tool()
async def list_objects(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    entity: Annotated[str, Field(description="The entity to list, e.g. 'Order' — as the contract names it.")],
    segment: Annotated[Optional[str], Field(
        description="A segment of it the contract names, e.g. 'late_dispatch' or 'overdue_dispatch'.")] = None,
    columns: Annotated[Optional[list[str]], Field(description="Properties to list beside the key (up to 8).")] = None,
    limit: Annotated[int, Field(description="Objects per page, at most 200.")] = 25,
    offset: Annotated[int, Field(description="Where the page starts.")] = 0,
    schema: Annotated[Optional[str], Field(description="The schema, when the connection has several.")] = None,
) -> dict:
    """Arc OC-8 — one page of a business entity's objects, or of a segment of them (late, overdue, a rule's
    objects), read through the published ontology: the key, the properties asked for, the total the set holds and
    the release it was read under. Each object is named `<object_type>:<key>` — the form a propose tool takes. Off
    unless an administrator turned on the doors for builders."""
    body = {"entity": entity, "segment": segment or "", "columns": list(columns or []), "limit": limit,
            "offset": offset}
    return await _client.list_objects(connection, body, schema=schema)


@mcp.tool()
async def get_table_health(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    table: Annotated[str, Field(description="The table to report health for.")],
) -> dict:
    """Data-quality verdicts for a table — which declared checks passed, which failed, how
    many violations, and how STALE each verdict is. Use it before trusting a number from a
    table: a verdict computed against yesterday's data is not authoritative today.
    `checked=false` means no checks have run — which is NOT the same as healthy."""
    return await _client.get_table_health(connection, table)


@mcp.tool()
async def list_trusted_queries(
    connection: Annotated[str, Field(description="A connection id from list_connections.")],
    limit: Annotated[int, Field(description="Max queries to return (default 25).", ge=1, le=100)] = 25,
) -> dict:
    """The verified query patterns for a connection, each with the WARRANT it carries:
    `human_pinned` (a person settled this question), `eval_promoted` (it passed every eval
    run), or `recorded`. Reuse the SQL structure of a trusted query rather than writing a
    new one — and prefer a human-pinned pattern over a promoted one when both exist."""
    return await _client.list_trusted_queries(connection, limit=limit)


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
        if _DYNAMIC.get(name) == "automations" and name in taken:
            continue                               # registered already (a live refresh)
        if name in taken:
            _log.warning("automation tool %r collides with an existing tool — skipped", name)
            continue
        from aughor.mcp.policy import tool_annotations
        mcp.add_tool(_automation_runner(api, automation_id), name=name,
                     description=_automation_description(row),
                     annotations=tool_annotations("act"))       # DE-2b: a run changes something
        taken.add(name)
        added.append(name)
        _DYNAMIC[name] = "automations"
    return added


async def register_spotlight_tools(client: "AughorClient | None" = None) -> list[str]:
    """SP-5 — register the DECLARED Spotlight roster, one tool per entry.

    Same posture as `register_automation_tools`: never raises, returns what it added,
    skips a name collision rather than shadowing. The declaration comes from the API's
    `/spotlight/tools` listing (the one roster every transport derives from) and each
    call goes back through the API — one process owns the stores; this one never does.
    Custody rides the roster, not the transport: every Act entry stages into the one
    inbox for a human, so nothing an MCP client invokes here executes anything.
    """
    api = client or _client
    try:
        declared = await api.list_spotlight_tools()
    except Exception as exc:                       # the API is down, or the route is old
        _log.warning("could not read the Spotlight roster: %s", exc)
        return []

    taken = set(getattr(mcp._tool_manager, "_tools", {}) or {})
    added: list[str] = []
    for row in declared:
        name = str(row.get("name") or "")
        if not name or (_DYNAMIC.get(name) == "spotlight" and name in taken):
            continue
        if name in taken:
            _log.warning("Spotlight tool %r collides with an existing tool — skipped", name)
            continue
        from aughor.mcp.policy import DYNAMIC_LEVELS, spotlight_tool_level, tool_annotations
        mcp.add_tool(_spotlight_runner(api, name), name=name,
                     description=_spotlight_description(row),
                     annotations=tool_annotations(spotlight_tool_level(name)))   # DE-2b
        _declare_arguments(name, _spotlight_input_schema(row))
        # The roster's split, said to the level map: by its name alone a roster read cannot be
        # told from an automation, and was read as an act — hidden under the default policy.
        DYNAMIC_LEVELS[name] = spotlight_tool_level(name)
        taken.add(name)
        added.append(name)
        _DYNAMIC[name] = "spotlight"
    return added


async def register_agent_tools(client: "AughorClient | None" = None) -> list[str]:
    """AO-5a — one tool per ENABLED custom agent: `ask_<slug>`, described by the agent's
    purpose, answering through `/ask` AS that agent (its brief, documents, packs, grants)
    with this process named as the principal. Same posture as the two registrars above:
    never raises, returns what it added, skips a collision rather than shadowing — an
    agent called "Ask" must not replace the governed `ask`.

    The caller is a principal (DE-2a's half that this transport can do today): the ask
    door attributes the turn to `mcp:<AUGHOR_MCP_PRINCIPAL or host>` when no session is in
    scope, so the agent's verdicts and spend know an MCP client asked, and which.
    """
    api = client or _client
    try:
        agents = await api.list_user_agents()
    except Exception as exc:                       # the API is down, or the route is old
        _log.warning("could not read the custom agents: %s", exc)
        return []

    from aughor.custom_agents.reach import mcp_tool_name
    taken = set(getattr(mcp._tool_manager, "_tools", {}) or {})
    added: list[str] = []
    for row in agents:
        if not row.get("enabled", True) or not row.get("id"):
            continue
        name = mcp_tool_name(_Row(row))
        if _DYNAMIC.get(name) == "agents" and name in taken:
            continue
        if name in taken:
            _log.warning("agent tool %r collides with an existing tool — skipped", name)
            continue
        from aughor.mcp.policy import DYNAMIC_LEVELS, tool_annotations
        mcp.add_tool(_agent_runner(api, str(row["id"]), str(row.get("connection_id") or "")),
                     name=name, description=_agent_description(row),
                     annotations=tool_annotations("run"))       # DE-2b: an ask spends; it changes nothing
        DYNAMIC_LEVELS[name] = "run"
        taken.add(name)
        added.append(name)
        _DYNAMIC[name] = "agents"
    return added


def ontology_scopes() -> list[tuple[str, str]]:
    """The scopes whose declared actions this server offers as propose tools: `AUGHOR_MCP_ONTOLOGY`, a comma-separated
    list of `<connection>` or `<connection>/<schema>`. Empty: no propose tools (the actions are per connection, and a
    tool must say which connection it proposes on)."""
    import os
    out = []
    for item in (os.environ.get("AUGHOR_MCP_ONTOLOGY") or "").split(","):
        conn, _, schema = item.strip().partition("/")
        if conn:
            out.append((conn, schema))
    return out


def _propose_tool_name(action_id: str, connection: str, taken: set[str]) -> str:
    name = f"propose_{action_id}"
    return name if name not in taken else f"{name}__{connection}"


async def _ontology_roster(api: "AughorClient") -> list[dict]:
    """One row per declared action of each configured scope, with the scope and the release it was read under."""
    rows: list[dict] = []
    for conn, schema in ontology_scopes():
        contract = await api.ontology_contract(conn, schema=schema or None)
        for action_id, action_schema in (contract.get("actions") or {}).items():
            rows.append({"action_id": action_id, "connection": conn, "schema": schema,
                         "release": contract.get("release") or "", "schema_json": action_schema})
    return rows


async def register_ontology_tools(client: "AughorClient | None" = None) -> list[str]:
    """Arc OC-8 — one tool per declared action of each configured scope: `propose_<action>`, whose input is the
    action's own JSON Schema from the published contract. Calling it PROPOSES — the proposal waits in the Actions inbox
    for a person, with the action's version pinned; nothing runs. Same posture as the registrars above: never raises,
    returns what it added, skips a name another tool holds."""
    api = client or _client
    try:
        rows = await _ontology_roster(api)
    except Exception as exc:                       # the API is down, the doors are off, or the route is old
        _log.warning("could not read the ontology contract: %s", exc)
        return []
    taken = set(getattr(mcp._tool_manager, "_tools", {}) or {})
    added: list[str] = []
    for row in rows:
        name = _propose_tool_name(row["action_id"], row["connection"],
                                  {t for t in taken if _DYNAMIC.get(t) != "ontology"})
        if _DYNAMIC.get(name) == "ontology" and name in taken:
            continue
        if name in taken:
            _log.warning("propose tool %r collides with an existing tool — skipped", name)
            continue
        from aughor.mcp.policy import DYNAMIC_LEVELS, tool_annotations
        declared = row["schema_json"]
        mcp.add_tool(_propose_runner(api, row), name=name,
                     description=(f"Propose '{declared.get('title')}' on connection {row['connection']} — "
                                  f"{declared.get('description') or ''} A person approves it in the Actions inbox; "
                                  f"nothing runs here. Contract {row['release'] or 'unreleased'}."),
                     annotations=tool_annotations("act"))
        schema = {k: v for k, v in declared.items() if k in ("type", "properties", "required")}
        schema["properties"] = {**schema.get("properties", {}), "reasoning": {
            "type": "string", "description": "Why — shown to the person who decides."}}
        _declare_arguments(name, schema)
        DYNAMIC_LEVELS[name] = "act"
        taken.add(name)
        added.append(name)
        _DYNAMIC[name] = "ontology"
    return added


def _propose_runner(api: "AughorClient", row: dict):
    """A factory, not a loop lambda — the late-binding trap the other runners refuse."""
    async def _run(**arguments: Any) -> Any:
        reasoning = str(arguments.pop("reasoning", "") or "")
        return await api.propose_action(row["connection"], row["action_id"],
                                        {k: v for k, v in arguments.items() if v is not None},
                                        reasoning=reasoning, release=row["release"], schema=row["schema"] or None)

    return _run


# ── The list is live: what appears and disappears at runtime does so for a connected client ──
#
# The three registrars above ran ONCE, at start, so an agent created, an automation exposed or
# a roster entry added afterwards reached a client only when it reconnected — and a tool whose
# agent was disabled or deleted stayed listed until a restart, failing when called. Now the
# rosters are re-read (at most every `_LIVE_TTL` seconds) whenever a client lists or calls a
# tool; what appeared is registered, what went is removed, and the server says so with
# `notifications/tools/list_changed` (`PolicedFastMCP.call_tool`) — the capability it declares.

#: name → the roster it came from ("automations" | "spotlight" | "agents").
_DYNAMIC: dict[str, str] = {}
#: The rosters this server keeps live — set ONLY by `enable_live_tools`, which the entry point
#: calls (`--no-…` skips one). A registrar never sets it: a test that registers against a stub
#: must not leave a later `list_tools` reading the real API (it did, once, in the full suite).
_LIVE_SOURCES: set[str] = set()


def enable_live_tools(*sources: str) -> None:
    """Keep these rosters live for a connected client: "automations", "spotlight", "agents"."""
    _LIVE_SOURCES.update(s for s in sources if s in ("automations", "spotlight", "agents", "ontology"))
_LIVE_TTL = 30.0
_live_checked: list[float] = []


def _roster_names(source: str, rows: list) -> set[str]:
    """The tool names a roster's rows would register as — the registrars' own naming."""
    if source == "automations":
        return {str(r.get("tool_name") or "") or automation_tool_name(str(r.get("name") or ""))
                for r in rows if str(r.get("id") or "")}
    if source == "spotlight":
        return {str(r.get("name")) for r in rows if r.get("name")}
    if source == "ontology":
        seen: set[str] = set()
        for r in rows:
            seen.add(_propose_tool_name(str(r.get("action_id")), str(r.get("connection")), seen))
        return seen
    from aughor.custom_agents.reach import mcp_tool_name
    return {mcp_tool_name(_Row(r)) for r in rows if r.get("enabled", True) and r.get("id")}


def _remove_tool(name: str) -> None:
    from aughor.mcp.policy import DYNAMIC_LEVELS
    getattr(mcp._tool_manager, "_tools", {}).pop(name, None)
    DYNAMIC_LEVELS.pop(name, None)
    _DYNAMIC.pop(name, None)


async def refresh_live_tools(client: "AughorClient | None" = None, *, force: bool = False) -> bool:
    """Re-read every live roster; register what appeared, remove what went. True when the
    list changed. Throttled to once per `_LIVE_TTL` unless ``force``. Never raises: a roster
    the API cannot serve right now is left exactly as it was, and that is logged."""
    import time as _time

    if not _LIVE_SOURCES:
        return False
    now = _time.monotonic()
    if not force and _live_checked and now - _live_checked[0] < _LIVE_TTL:
        return False
    _live_checked[:] = [now]
    api = client or _client
    readers = {"automations": (api.list_automation_tools, register_automation_tools),
               "spotlight": (api.list_spotlight_tools, register_spotlight_tools),
               "agents": (api.list_user_agents, register_agent_tools),
               "ontology": (lambda: _ontology_roster(api), register_ontology_tools)}
    changed = False
    for source in sorted(_LIVE_SOURCES):
        read, register = readers[source]
        try:
            rows = list(await read() or [])
        except Exception as exc:
            _log.warning("live tools: could not re-read the %s roster (%s); left as it was", source, exc)
            continue
        ours = {n for n, src in _DYNAMIC.items() if src == source}
        others = set(getattr(mcp._tool_manager, "_tools", {}) or {}) - ours
        wanted = _roster_names(source, rows) - others
        for name in sorted(ours - wanted):
            _remove_tool(name)
            changed = True
        if wanted - ours:
            changed = bool(await register(api)) or changed
    return changed


class _Row:
    """A dict row with attribute access, for the one helper that reads `.name`/`.id`."""
    def __init__(self, row: dict):
        self.id = str(row.get("id") or "")
        self.name = str(row.get("name") or "")


def _agent_description(row: dict) -> str:
    purpose = str(row.get("purpose") or "").strip()
    scope = str(row.get("schema_scope") or "").strip()
    conn = str(row.get("connection_id") or "").strip()
    desc = f"Ask the custom agent '{row.get('name')}'"
    desc += f" — {purpose}" if purpose else " (no purpose written; its instructions decide)"
    desc += f". Answers on connection {conn}" if conn else ". Answers on the connection you name"
    desc += f", schema {scope}" if scope else ""
    desc += (". Returns the agent's own answer: headline, the SQL that ran, rows and a receipt; "
             "the agent's grants only ever PROPOSE, never execute.")
    return desc


def _agent_runner(api: "AughorClient", agent_id: str, connection_id: str):
    """A factory, not a loop lambda (the late-binding trap the other runners refuse)."""
    import os
    import socket

    async def run(
        question: Annotated[str, Field(description="The question for this agent, in plain words.")],
        connection: Annotated[Optional[str], Field(
            description="A connection id from list_connections; only needed when the agent is unbound.")] = None,
        asker: Annotated[Optional[str], Field(
            description="Who is asking, for attribution (an email or a service name).")] = None,
    ) -> dict:
        who = asker or os.environ.get("AUGHOR_MCP_PRINCIPAL") or socket.gethostname()
        return await api.ask_as_agent(agent_id, question, connection or connection_id, asker=who)

    return run


def _spotlight_description(row: dict) -> str:
    """The declared description IS the routing policy on this transport too. The arguments
    are no longer rendered into it: each tool carries the roster's own JSON Schema."""
    return str(row.get("description") or "").strip()


def _spotlight_input_schema(row: dict) -> dict:
    """The tool's input schema: the roster's declared parameters VERBATIM — types, enums,
    `required`, descriptions — plus `connection`. Before this every Spotlight tool took one
    opaque `args` object, and a client saw its arguments only as prose in the description."""
    declared = dict(row.get("parameters") or {})
    props = dict(declared.get("properties") or {})
    props.setdefault("connection", {
        "type": "string",
        "description": "A connection id from list_connections — the connection-flavoured tools "
                       "need it; organisation-level reads ignore it."})
    schema = {**declared, "type": "object", "properties": props}
    if declared.get("required"):
        schema["required"] = [r for r in declared["required"] if r in props]
    return schema


class _DeclaredArguments(ArgModelBase):
    """FastMCP builds a tool's argument model from the runner's signature. A roster tool's
    arguments are declared as JSON Schema instead, so this model carries them through
    untouched; the API validates them on the call, as it does for every transport."""
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


def _declare_arguments(name: str, schema: dict) -> None:
    """Give a registered tool its declared schema (what `tools/list` shows) and the
    pass-through argument model. A stub tool manager (tests) holds no Tool — a no-op there."""
    tools = getattr(mcp._tool_manager, "_tools", None)
    tool = tools.get(name) if isinstance(tools, dict) else None
    if tool is None or not hasattr(tool, "fn_metadata"):
        return
    tools[name] = tool.model_copy(update={
        "parameters": schema,
        "fn_metadata": tool.fn_metadata.model_copy(update={"arg_model": _DeclaredArguments})})


def _spotlight_runner(api: "AughorClient", name: str):
    """A factory, not a loop lambda — the same late-binding trap the automation
    runner already refuses. `connection` binds the connection-flavoured tools;
    org-level reads ignore it."""
    async def _run(**arguments: Any) -> Any:
        connection = str(arguments.pop("connection", "") or "")
        return await api.call_spotlight_tool(
            name, connection=connection,
            args={k: v for k, v in arguments.items() if v is not None})

    return _run


# ── DE-2a (ROADMAP §3.51): the HTTP transport has a door ─────────────────────────
#
# Measured on 2026-10-03 before this existed, `--http --host 0.0.0.0` on this machine: a
# loopback client with no credential at all got a full session (the tools then call the
# API with THIS process's key and principal), and a remote client got `421 Invalid Host
# header` on every request — FastMCP fixes a loopback-only host allowlist when the
# `FastMCP` object is built at import, before `--host` is read, so the flag served nobody
# it was meant to serve. Two rules now: every HTTP request carries a bearer token the
# operator set (`AUGHOR_MCP_TOKEN`), compared in constant time; and the transport security
# is built for the host actually served, as FastMCP would have built it had it known.

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def transport_security_for(host: str) -> TransportSecuritySettings:
    """FastMCP's own transport-security posture, for the host actually served.

    Loopback keeps FastMCP's DNS-rebinding protection with its loopback allowlist. Any other host gets what
    FastMCP gives a non-loopback host it is told about at construction — protection off, since the names a
    remote client will put in `Host` cannot be enumerated here — and the bearer gate is the door instead."""
    if host in _LOOPBACK_HOSTS:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


class BearerGate:
    """Pure-ASGI: every HTTP request presents ``Authorization: Bearer <token>`` or is refused with a 401.

    The comparison is constant-time (`hmac.compare_digest`), the refusal names what is missing and carries a
    `WWW-Authenticate` challenge, and nothing else is read from the request — the MCP app behind the gate
    decides everything else."""

    def __init__(self, app: Any, token: str) -> None:
        if not token:
            raise ValueError("BearerGate needs a token")
        self.app = app
        self._token = token.encode("utf-8")

    def _presented(self, scope: dict) -> bytes:
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                scheme, _, credential = value.partition(b" ")
                return credential.strip() if scheme.lower() == b"bearer" else b""
        return b""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        presented = self._presented(scope)
        if presented and hmac.compare_digest(presented, self._token):
            return await self.app(scope, receive, send)
        body = (b'{"error":"unauthorized","detail":"this MCP server requires `Authorization: Bearer <token>`; '
                b'the token is AUGHOR_MCP_TOKEN on the server"}')
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b'Bearer realm="aughor-mcp"'),
        ]})
        await send({"type": "http.response.body", "body": body})


def http_app(token: str, host: str):
    """The streamable-HTTP app behind the bearer gate, with its transport security built for ``host``.

    Set BEFORE `streamable_http_app()`: FastMCP creates its session manager on the first call and bakes the
    security settings into it, so this is called once, from the entry point, before anything is served."""
    mcp.settings.host = host
    mcp.settings.transport_security = transport_security_for(host)
    return BearerGate(mcp.streamable_http_app(), token)


def serve_http(host: str, port: int, token: str) -> None:
    """Serve `http_app` with uvicorn — what `mcp.run(transport="streamable-http")` does, with the door in front."""
    import uvicorn

    mcp.settings.port = port
    uvicorn.run(http_app(token, host), host=host, port=port, log_level=mcp.settings.log_level.lower())


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
