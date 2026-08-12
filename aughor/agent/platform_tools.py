"""CI-2 — the platform tool roster: read tools over every surface the platform has.

Wave 5 proved the inversion on one surface (the quick-answer pipeline as a tool); this
module extends it to the rest of the platform. The conversation is the interface to the
whole product — ontology and glossary, stored findings, the briefing, monitors, packs,
the platform itself — and each of those surfaces becomes a tool the model may choose,
never a capability it re-implements.

Three rules, inherited rather than invented:

* **One body, two callers.** Where an MCP knowledge tool already reads a surface
  (:mod:`aughor.mcp.knowledge_tools`, Wave S6), the converse tool calls the SAME body, so
  an external agent over MCP and the platform's own conversation cannot disagree about
  what Aughor knows. The MCP docstrings are the routing policy here too — same names,
  same claims, compressed to the wire.
* **Read-only means read-only.** `get_briefing` reads the cached narrative via
  ``peek_briefing`` and NEVER synthesizes — a read tool that could spend an LLM call plus
  a coverage fan-out on a cache miss would make "look something up" the most expensive
  sentence in the product. What is not built yet is reported as absent, not built on
  demand.
* **The context window is the budget.** Every result is capped and compacted before it
  reaches the model — the ``_MAX_PREVIEW_ROWS`` lesson (re-injection measured 3.5× at 8
  steps). Truncation always says so: a capped list with no marker reads as "that is
  everything", and the model will report it that way, confidently.

Writes are deliberately absent. The tier decision is on record (personal, reversible
artifacts write directly; shared/org semantic state is proposal-only), but the personal
substrate (saved queries, pins) does not exist yet — a write tool with nowhere durable to
write would be theater. The roster grows when the store does.
"""
from __future__ import annotations

import logging

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

#: Caps, chosen for the context window rather than the store. Findings and search hits
#: are cited by the model verbatim; monitors and queries are scanned. All say when cut.
_MAX_SEARCH_HITS = 8
_MAX_FINDINGS = 12
_MAX_TRUSTED = 10
_MAX_MONITORS = 25
_MAX_ALERTS = 5
_MAX_CITATIONS = 10
_MAX_RELATED = 20
_SQL_PREVIEW = 400


def search_graph(connection_id: str, args: dict) -> dict:
    """Search the connection's knowledge graph — the shared MCP body, plus staleness.

    Staleness rides the result because a search over a stale graph is a different claim
    than one over a fresh graph, and the model has no other way to know which it made.
    """
    from aughor.mcp.knowledge_tools import search_graph as _search

    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "no query supplied"}

    limit = _cap(args.get("limit"), _MAX_SEARCH_HITS, hard=20)
    out = _search(connection_id, query, limit=limit)
    # Compact for the window: `data` blobs carry column lists and provenance the entity
    # page needs but a routing decision does not — `describe_entity` is the paid detail.
    out["nodes"] = [
        {"id": n.get("id"), "kind": n.get("kind"), "label": n.get("label"),
         "summary": n.get("summary", "")}
        for n in out.get("nodes", [])
    ]
    out["staleness"] = _graph_staleness(connection_id)
    return out


def describe_entity(connection_id: str, args: dict) -> dict:
    """One entity's semantic slice — the shared MCP body, related edges capped."""
    from aughor.mcp.knowledge_tools import describe_entity as _describe

    entity = str(args.get("entity") or "").strip()
    if not entity:
        return {"error": "no entity supplied"}

    out = _describe(connection_id, entity)
    related = out.get("related") or []
    if len(related) > _MAX_RELATED:
        out["related"] = related[:_MAX_RELATED]
        out["related_truncated"] = True
    return out


def get_table_health(connection_id: str, args: dict) -> dict:
    """Quality verdicts for one table — the shared MCP body, unchanged."""
    from aughor.mcp.knowledge_tools import get_table_health as _health

    table = str(args.get("table") or "").strip()
    return _health(connection_id, table)


def list_trusted_queries(connection_id: str, args: dict) -> dict:
    """Verified query patterns with their warrants — the shared MCP body, capped."""
    from aughor.mcp.knowledge_tools import list_trusted_queries as _trusted

    return _trusted(connection_id, limit=_cap(args.get("limit"), _MAX_TRUSTED, hard=25))


def list_findings(connection_id: str, args: dict) -> dict:
    """The explorer's stored findings — pre-computed, so a $0 read.

    Resolves the same way the findings endpoint does (per-schema aggregate when the
    connection ran per-schema, else the connection state) and filters quarantined
    findings the same way the store's own readers do — a finding the user dismissed
    must not resurface in chat wearing fresh confidence.
    """
    from aughor.explorer import store as _store

    if _store.schema_run_keys(connection_id):
        state = _store.load_aggregate(connection_id)
    else:
        state = _store.load(connection_id)

    # The store's legacy state key, read as data; this roster's vocabulary is "findings".
    findings = [f for f in state.get("insights", []) if not f.get("invalid")]
    limit = _cap(args.get("limit"), _MAX_FINDINGS, hard=25)
    out = []
    for f in findings[:limit]:
        entry = {
            "id": f.get("id"),
            "finding": f.get("finding"),
            "domain": f.get("domain"),
            "confidence": f.get("confidence"),
            "novelty": f.get("novelty"),
        }
        if f.get("sql"):
            entry["sql"] = str(f["sql"])[:_SQL_PREVIEW]
        out.append(entry)
    return {
        "phase": state.get("phase", "pending"),
        "count": len(findings),
        "findings": out,
        "truncated": len(findings) > limit,
    }


def get_briefing(connection_id: str, args: dict) -> dict:
    """The cached executive briefing — READ ONLY, never synthesizes.

    ``peek_briefing`` is the whole point of this body: the generating read costs an LLM
    call plus a coverage fan-out on a miss, which is not a price a lookup tool may
    quietly pay. Absent means absent.

    A connection explored per-schema caches its briefs under ``{conn}:{schema}``, so the
    bare-connection peek alone would say "no briefing exists" about a connection whose
    Briefing page is showing one. The fallback names the schemas that DO have briefs and
    serves one when asked (or when there is only one) — the reason must never claim
    more absence than is true.
    """
    from aughor.knowledge.briefing import peek_briefing

    schema = str(args.get("schema") or "").strip()
    scope_key = f"{connection_id}:{schema}" if schema else connection_id
    brief = peek_briefing(scope_key)
    if not brief and not schema:
        with_briefs = _schemas_with_briefs(connection_id)
        if len(with_briefs) == 1:
            schema = with_briefs[0]
            brief = peek_briefing(f"{connection_id}:{schema}")
        elif with_briefs:
            return {"available": False,
                    "reason": "no connection-wide briefing is cached, but per-schema "
                              f"briefings exist for: {', '.join(with_briefs)} — call "
                              "again with `schema` set to one of them"}
    if not brief:
        return {"available": False,
                "reason": "no briefing has been synthesized for this scope yet — "
                          "the Briefing page builds one from the explorer's findings"}
    citations = list(brief.get("citations") or [])
    return {
        "available": True,
        **({"schema": schema} if schema else {}),
        "narrative": brief.get("narrative", ""),
        "headline_theme": brief.get("headline_theme", ""),
        "citations": citations[:_MAX_CITATIONS],
        "citations_truncated": len(citations) > _MAX_CITATIONS,
        "generated_at": brief.get("generated_at"),
    }


def _schemas_with_briefs(connection_id: str) -> list[str]:
    """The schemas of this connection's per-schema runs that have a cached brief."""
    try:
        from aughor.explorer.store import schema_run_keys
        from aughor.knowledge.briefing import peek_briefing

        prefix = f"{connection_id}__"
        schemas = [k[len(prefix):] for k in schema_run_keys(connection_id)]
        return [s for s in schemas if peek_briefing(f"{connection_id}:{s}")]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the per-schema fallback is additive; the bare peek already ran",
                 counter="platform_tools.schema_briefs")
        return []


def list_monitors(connection_id: str, args: dict) -> dict:
    """The connection's monitors and their alert state, compacted for a status answer."""
    from aughor.monitors import store as _store

    monitors = _store.list_monitors(connection_id)
    out = []
    for m in monitors[:_MAX_MONITORS]:
        watches = m.metric_name or m.freshness_table or "custom SQL"
        out.append({
            "id": m.id, "name": m.name, "watches": watches,
            "kind": m.alert_on, "enabled": m.enabled, "cadence": m.check_cron,
        })
    unacked = _store.get_alerts(conn_id=connection_id, unacknowledged_only=True,
                                limit=100)
    recent = [{
        "monitor": a.monitor_name, "severity": a.severity,
        "triggered_at": a.triggered_at, "message": str(a.message or "")[:200],
    } for a in unacked[:_MAX_ALERTS]]
    return {
        "count": len(monitors),
        "monitors": out,
        "truncated": len(monitors) > _MAX_MONITORS,
        "unacknowledged_alerts": len(unacked),
        "recent_alerts": recent,
    }


def list_packs(connection_id: str, args: dict) -> dict:
    """Installed specialist packs, and which one is bound to THIS connection.

    The bound pack answers with its playbooks — that is the piece a conversation can
    actually use ("what would the finance pack look at here"), and it is only fetched
    for the one pack whose detail matters.
    """
    from aughor.packs import load_binding, load_pack, list_packs as _list_packs
    from aughor.routers.packs import PACKS_DIR

    if not PACKS_DIR.is_dir():
        return {"count": 0, "packs": []}

    packs = []
    for pack_id in _list_packs(PACKS_DIR):
        entry: dict = {"id": pack_id}
        try:
            pack = load_pack(PACKS_DIR / pack_id)
            entry.update({"name": pack.manifest.name, "status": pack.manifest.status,
                          "domains": pack.manifest.domains})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "an unloadable pack is listed by id, not hidden",
                     counter="platform_tools.pack_load")
            entry["error"] = "pack failed to load"
            packs.append(entry)
            continue
        try:
            binding = load_binding(pack_id, connection_id)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a corrupt binding file must not take the whole roster down",
                     counter="platform_tools.pack_binding")
            binding = None
        entry["bound_to_this_connection"] = bool(binding)
        if binding:
            entry["playbooks"] = [
                {"trigger": " ".join(filter(None, (p.trigger_metric, p.trigger_operator,
                                                   p.trigger_condition))),
                 "recommendation": str(p.recommendation or "")[:200]}
                for p in pack.playbooks[:8]
            ]
        packs.append(entry)
    return {"count": len(packs), "packs": packs}


# ── platform help ────────────────────────────────────────────────────────────────────
#
# Curated, static, deterministic — the meta tool answers "what can you do" and "how do
# I…" from a hand-written map of the product, not from an LLM's impression of it. Kept
# here rather than in docs/ because the tool IS the doc's consumer: a topic nobody
# routes to is a topic this dict should not carry.

_HELP_TOPICS: dict[str, str] = {
    "overview": (
        "Aughor is a governed data-intelligence platform over your connected "
        "warehouse. It writes and runs the SQL itself, grounds every number in real "
        "rows, enforces registered metric definitions, and attaches a Trust Receipt "
        "(the guards that fired) to each answer. In this chat you can ask analytical "
        "questions, run specific SQL, look up what Aughor has already discovered "
        "(findings, the briefing, the knowledge graph), and check monitors, data "
        "health, packs and saved query patterns."
    ),
    "connect": (
        "Add a warehouse from the Connections page (the plug icon in the sidebar): "
        "choose the engine — for example Snowflake, Postgres, BigQuery or DuckDB — "
        "and supply its credentials or connection string. Registering requires the "
        "server's secret key to be configured; a connection registered without it "
        "fails. After connecting, run an exploration so Aughor can profile the data "
        "and start discovering findings."
    ),
    "explore": (
        "Exploration is Aughor's autonomous background discovery: it profiles the "
        "data, maps entities and lifecycles, and surfaces verified findings with no "
        "prompting. Start it from a connection's page. Findings accumulate in the "
        "store and are pre-computed — asking about them costs nothing."
    ),
    "briefing": (
        "The Briefing is the synthesized, impact-ranked narrative of what matters "
        "right now, built from the explorer's findings and the governed north-star "
        "metrics. It is generated on the Briefing page and cached; this chat can "
        "read the current one but does not rebuild it."
    ),
    "analysis": (
        "Ask direct questions in this chat for governed answers. For open-ended "
        "why / root-cause / driver questions, Analysis Mode runs a multi-step "
        "deep analysis: it forms hypotheses, gathers and verifies evidence, and "
        "synthesizes a report with recommendations and a Trust Receipt."
    ),
    "monitors": (
        "Monitors watch a metric, a table's freshness, or a custom SQL value on a "
        "schedule and raise alerts (warning or critical) when thresholds or "
        "anomaly checks trip. Create and manage them on the Monitors page; this "
        "chat can list them and report current alert status."
    ),
    "packs": (
        "Specialist packs bundle domain expertise — metrics, entity roles, "
        "playbooks and evals for a vertical. A pack is bound to a connection "
        "before it steers anything, and binding proposals are reviewed rather than "
        "auto-applied."
    ),
    "governance": (
        "Registered metrics carry governed definitions that every answer must use; "
        "the glossary and ontology hold what tables, columns and terms mean; the "
        "guard battery checks each query (joins, grains, fan-out, nulls) and its "
        "receipts ride with each answer. Edits to shared semantics are proposals "
        "for review, not silent writes."
    ),
}

_HELP_ALIASES = {
    "capabilities": "overview", "help": "overview", "about": "overview",
    "snowflake": "connect", "warehouse": "connect", "connection": "connect",
    "connections": "connect",
    "exploration": "explore", "findings": "explore",
    "briefings": "briefing", "brief": "briefing",
    "deep analysis": "analysis", "investigate": "analysis", "why": "analysis",
    "alerts": "monitors", "monitor": "monitors",
    "pack": "packs", "playbooks": "packs",
    "metrics": "governance", "glossary": "governance", "ontology": "governance",
    "guards": "governance", "receipts": "governance",
}


def platform_help(connection_id: str, args: dict) -> dict:
    """What Aughor is and how to use it — curated text, no model, no network."""
    topic = str(args.get("topic") or "").strip().lower()
    resolved = _HELP_ALIASES.get(topic, topic) or "overview"
    if resolved in _HELP_TOPICS:
        return {"topic": resolved, "help": _HELP_TOPICS[resolved],
                "topics": sorted(_HELP_TOPICS)}
    # An unknown topic is an answer (P2): name what CAN be asked, don't guess.
    return {"topic": topic, "help": _HELP_TOPICS["overview"],
            "note": f"no specific help for {topic!r}; topics listed",
            "topics": sorted(_HELP_TOPICS)}


# ── helpers ──────────────────────────────────────────────────────────────────────────

def _cap(raw, default: int, *, hard: int) -> int:
    try:
        n = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(1, min(n, hard))


def _graph_staleness(connection_id: str) -> str:
    try:
        from aughor.ontology.graph_freshness import staleness_of
        return str(staleness_of(connection_id))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "staleness is additive context on a search result",
                 counter="platform_tools.staleness")
        return "unknown"


# ── the roster ───────────────────────────────────────────────────────────────────────

_QUERY_PARAMS = {
    "type": "object",
    "properties": {
        "query": {"type": "string",
                  "description": "What to look for — a table, metric, term or topic."},
        "limit": {"type": "integer", "description": "Max results (default 8)."},
    },
    "required": ["query"],
}
_ENTITY_PARAMS = {
    "type": "object",
    "properties": {"entity": {"type": "string",
                              "description": "A table or entity name, e.g. 'orders'."}},
    "required": ["entity"],
}
_HEALTH_PARAMS = {
    "type": "object",
    "properties": {"table": {"type": "string",
                             "description": "The table to report health for."}},
    "required": ["table"],
}
_LIMIT_PARAMS = {
    "type": "object",
    "properties": {"limit": {"type": "integer", "description": "Max results."}},
}
_EMPTY_PARAMS: dict = {"type": "object", "properties": {}}
_BRIEFING_PARAMS = {
    "type": "object",
    "properties": {"schema": {
        "type": "string",
        "description": "Optional schema name, only when the result names schemas "
                       "that have briefings.",
    }},
}
_HELP_PARAMS = {
    "type": "object",
    "properties": {"topic": {
        "type": "string",
        "description": "Optional topic: overview, connect, explore, briefing, "
                       "analysis, monitors, packs, governance.",
    }},
}


def platform_tools(connection_id: str) -> list[ToolSpec]:
    """The read roster for one connection — bound by closure, like every converse tool.

    Descriptions are the routing policy (P3), compressed from the MCP server's
    docstrings so the two surfaces route by the same claims.
    """
    return [
        ToolSpec(
            name="search_graph",
            description=(
                "Search what Aughor has already established about this connection — "
                "tables, governed metrics, glossary terms and past findings, with "
                "graph staleness. A $0 read: prefer it before re-deriving anything "
                "with SQL. Use describe_entity for full detail on one result."
            ),
            parameters=_QUERY_PARAMS,
            run=lambda a: search_graph(connection_id, a),
        ),
        ToolSpec(
            name="describe_entity",
            description=(
                "Everything Aughor has LEARNED about one table or entity — verified "
                "joins with measured overlap, glossary terms, related findings. "
                "Semantic knowledge, not raw columns: use describe_table for the "
                "physical schema."
            ),
            parameters=_ENTITY_PARAMS,
            run=lambda a: describe_entity(connection_id, a),
        ),
        ToolSpec(
            name="list_findings",
            description=(
                "The findings Aughor's background exploration already discovered — "
                "each verified, with confidence and the SQL behind it. Pre-computed: "
                "check here before running new analysis on a broad question like "
                "'what's interesting in this data'."
            ),
            parameters=_LIMIT_PARAMS,
            run=lambda a: list_findings(connection_id, a),
        ),
        ToolSpec(
            name="get_briefing",
            description=(
                "The current executive briefing — the synthesized, impact-ranked "
                "narrative of what matters now, with citations. Cached read only; "
                "if none exists, say so and point the user at the Briefing page."
            ),
            parameters=_BRIEFING_PARAMS,
            run=lambda a: get_briefing(connection_id, a),
        ),
        ToolSpec(
            name="get_table_health",
            description=(
                "Data-quality verdicts for a table — which declared checks pass or "
                "fail, and how stale each verdict is. Use before leaning on a table's "
                "numbers; `checked=false` means unverified, NOT healthy."
            ),
            parameters=_HEALTH_PARAMS,
            run=lambda a: get_table_health(connection_id, a),
        ),
        ToolSpec(
            name="list_trusted_queries",
            description=(
                "Verified query patterns for this connection, each with its warrant "
                "(human-pinned beats eval-promoted beats recorded). Reuse a trusted "
                "query's SQL structure instead of writing a new one when a question "
                "matches."
            ),
            parameters=_LIMIT_PARAMS,
            run=lambda a: list_trusted_queries(connection_id, a),
        ),
        ToolSpec(
            name="list_monitors",
            description=(
                "The monitors watching this connection (metric, freshness, drift) "
                "and their current alert state, including unacknowledged alerts. "
                "The answer to 'is anything alerting' and 'what is being watched'."
            ),
            parameters=_EMPTY_PARAMS,
            run=lambda a: list_monitors(connection_id, a),
        ),
        ToolSpec(
            name="list_packs",
            description=(
                "Installed specialist packs (domain expertise bundles) and whether "
                "one is bound to this connection — the bound pack includes its "
                "playbooks. For 'what domain expertise is active here'."
            ),
            parameters=_EMPTY_PARAMS,
            run=lambda a: list_packs(connection_id, a),
        ),
        ToolSpec(
            name="platform_help",
            description=(
                "How Aughor itself works — connecting a warehouse, exploration, "
                "briefings, analysis modes, monitors, packs, governance. Use for "
                "questions about the PRODUCT ('what can you do', 'how do I connect "
                "Snowflake'), never for questions about the data."
            ),
            parameters=_HELP_PARAMS,
            run=lambda a: platform_help(connection_id, a),
        ),
    ]
