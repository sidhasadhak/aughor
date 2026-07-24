"""Agent plugin registration — the plug-and-play manifest.

The Platform exposes registries (purge hooks, and — later — schema annotators,
ingestion sinks, post-execute hooks) but never imports the Agent. The Agent plugs
*in* by registering its contributions here. ``register_agent_plugins()`` is called
once at every host entry point — the API lifespan, the CLI, and the test-session
conftest — so the agent's intelligence is live on the platform's seams.

Idempotent: a module-level guard makes a second call a no-op, so the API lifespan
re-registering after the conftest already did is safe (double-registration would
double-run the hooks and corrupt the cascade counts — the guard prevents that).
"""
from __future__ import annotations

_REGISTERED = False


def register_agent_plugins() -> None:
    """Wire every Agent contribution into the Platform's registries. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    _register_purge_hooks()
    _register_ingest_sinks()
    _register_schema_annotators()
    _register_execution_hooks()
    _register_authz_resolvers()
    _register_value_sample_loader()
    _REGISTERED = True


def _register_value_sample_loader() -> None:
    """R5 — the profiler's persisted entity-value samples, readable by the platform's
    filter guard through the registry seam (no Platform→Agent import)."""
    from aughor.kernel.registries.value_samples import register_value_sample_loader

    def _load(connection_id: str) -> dict:
        from aughor.tools.profile_cache import load_value_samples
        return load_value_samples(connection_id)

    register_value_sample_loader(_load)


# ── Authz resolvers (Pattern C) — invert security/authz's reach into agent stores ─

def _register_authz_resolvers() -> None:
    """Map an agent resource id → its connection id, so object-level authz can resolve
    its tenant (conn→org) without the platform importing the agent's stores."""
    from aughor.kernel.registries import resource_org as rreg

    def _monitor_conn(monitor_id: str):
        from aughor.monitors.store import get_monitor
        m = get_monitor(monitor_id)
        return m.conn_id if m else None

    def _alert_conn(alert_id: str):
        from aughor.monitors.store import get_alert
        a = get_alert(alert_id)
        return a.conn_id if a else None

    def _brief_conn(sub_id: str):
        from aughor.briefs.store import get_subscription
        sub = get_subscription(sub_id)
        return sub.conn_id if sub else None

    rreg.register_resource_conn_resolver("monitor", _monitor_conn)
    rreg.register_resource_conn_resolver("alert", _alert_conn)
    rreg.register_resource_conn_resolver("brief", _brief_conn)


# ── Schema annotators (Pattern B) — invert db/connection.py's schema enrichment ─

def _register_schema_annotators() -> None:
    from aughor.agent import schema_annotators
    schema_annotators.register()


# ── Execution hooks (Pattern B) — invert the semops ai_sql reach-ins ───────────

def _register_execution_hooks() -> None:
    from aughor.kernel.registries import execution_hooks as eh

    def _ai_column_receipt(sql, result, connection_id):
        # R8: provenance for an in-SQL AI column — when a query computed one via the
        # governed prompt()/embedding() UDF, journal an ai.column receipt.
        from aughor.semops.ai_sql import ai_sql_enabled, sql_uses_ai_column
        _op = sql_uses_ai_column(sql) if ai_sql_enabled() else None
        if _op:
            from aughor.semops.ai_sql import AIColumnReceipt, emit_ai_receipt
            _rows = getattr(result, "row_count", 0) or 0
            _rc = AIColumnReceipt(operator=_op, template="(in-SQL UDF)", role="", model="",
                                  n_input=_rows, n_applied=_rows)
            _rc.notes.append("computed in-SQL via the governed UDF")
            emit_ai_receipt(_rc, conn_id=connection_id)

    def _ai_udfs(raw_conn, *, is_motherduck=False):
        # MotherDuck has NATIVE prompt()/embedding() — don't shadow them.
        if is_motherduck:
            return
        from aughor.semops.ai_sql import ai_sql_enabled, register_ai_udfs
        if ai_sql_enabled():
            register_ai_udfs(raw_conn)

    eh.register_post_execute_hook("ai_column_receipt", _ai_column_receipt)
    eh.register_on_connect_hook("ai_udfs", _ai_udfs)


# ── Ingestion sinks (Pattern D) — invert connector → knowledge.indexer ─────────

def _register_ingest_sinks() -> None:
    from aughor.kernel.registries import ingestion

    def _knowledge_sink(**doc):
        from aughor.knowledge.indexer import index_text
        return index_text(**doc)

    def _investigation_index_sink(*, inv_id, question, headline, key_findings,
                                  connection_id, query_history):
        from aughor.tools.prior_analyses import index_investigation, index_sql_examples
        index_investigation(inv_id, question=question, headline=headline,
                            key_findings=key_findings, connection_id=connection_id)
        if question and query_history:
            index_sql_examples(inv_id, question=question, query_history=query_history,
                               connection_id=connection_id)
        return {}

    def _connection_invalidated_sink(*, conn_id):
        from aughor.tools.profile_cache import invalidate
        invalidate(conn_id)
        return {}

    ingestion.register_ingest_sink("knowledge", _knowledge_sink)
    ingestion.register_ingest_sink("investigation_index", _investigation_index_sink)
    ingestion.register_ingest_sink("connection_invalidated", _connection_invalidated_sink)


# ── Purge hooks (Pattern C) — invert db/purge.py's agent-store cascade ─────────

def _register_purge_hooks() -> None:
    from aughor.kernel.registries import purge_hooks as ph

    # connection-keyed
    ph.register_purge_hook("ontology", _ontology_conn)
    ph.register_purge_hook("profile", _profile_conn)
    ph.register_purge_hook("profile_cache", _profile_cache_conn)
    ph.register_purge_hook("briefs", _briefs_conn)
    ph.register_purge_hook("knowledge_cache", _knowledge_cache_conn)
    ph.register_purge_hook("monitors", _monitors_conn)
    ph.register_purge_hook("automations", _automations_conn)
    ph.register_purge_hook("connection_kb", _connection_kb_conn)
    ph.register_purge_hook("packs", _packs_conn)
    ph.register_purge_hook("evidence", _evidence_conn)
    ph.register_purge_hook("ambiguity_ledger", _ambiguity_conn)
    ph.register_purge_hook("overlay_ledger", _overlay_conn)
    ph.register_purge_hook("qdrant", _qdrant_conn)

    # schema-keyed
    ph.register_schema_purge_hook("profile", _profile_schema)
    ph.register_schema_purge_hook("ontology", _ontology_schema)
    ph.register_schema_purge_hook("knowledge_cache", _knowledge_schema)
    ph.register_schema_purge_hook("watermark", _watermark_schema)
    ph.register_schema_purge_hook("packs", _packs_schema)
    ph.register_schema_purge_hook("profile_cache", _profile_cache_schema)
    ph.register_schema_purge_hook("monitors", _monitors_schema)

    # investigation-keyed
    ph.register_investigations_purge_hook("evidence", _evidence_inv)
    ph.register_investigations_purge_hook("qdrant", _qdrant_inv)


# connection-keyed hooks ------------------------------------------------------

def _ontology_conn(conn_id, org_id):
    from aughor.ontology import store as ontology_store
    ontology_store.invalidate(conn_id)
    return {"ontology": 1}


def _profile_conn(conn_id, org_id):
    from aughor.profile import store as profile_store
    profile_store.invalidate(conn_id)
    return {"profile": 1}


def _profile_cache_conn(conn_id, org_id):
    from aughor.tools import profile_cache
    profile_cache.invalidate(conn_id)
    return {"profile_cache": 1}


def _briefs_conn(conn_id, org_id):
    from aughor.briefs import store as brief_store
    return {"brief_subscriptions": brief_store.delete_for_connection(conn_id)}


def _knowledge_cache_conn(conn_id, org_id):
    from aughor.knowledge import briefing, patterns
    return {"briefing_cache": briefing.invalidate(conn_id),
            "patterns_cache": patterns.invalidate(conn_id)}


def _monitors_conn(conn_id, org_id):
    from aughor.monitors import store as monitor_store
    return {"monitors": monitor_store.purge_connection(conn_id)}


def _automations_conn(conn_id, org_id):
    # Wave A1: an automation and its tick history are bound to one connection — a condition
    # probes it and every effect targets it — so both die with the connection.
    from aughor.automations import store as automation_store
    return {"automations": automation_store.purge_connection(conn_id)}


def _connection_kb_conn(conn_id, org_id):
    from aughor.semantic import connection_kb
    return {"knowledge": connection_kb.purge_connection(conn_id)}


def _packs_conn(conn_id, org_id):
    from aughor.packs import bindings, deltastore
    return {"pack_bindings": bindings.purge_connection(conn_id),
            "pack_deltas": deltastore.purge_connection(conn_id)}


def _evidence_conn(conn_id, org_id):
    # Reads the live investigation ids (history is platform) and drops their evidence
    # BEFORE the platform deletes the history rows — same ordering db/purge.py had.
    from aughor.db import history
    from aughor.evidence import store as evidence_store
    inv_ids = history.list_investigation_ids(conn_id, limit=100000)
    return {"evidence_claims": evidence_store.purge_investigations(inv_ids)}


def _ambiguity_conn(conn_id, org_id):
    # Drop every crystallized ambiguity resolution for the deleted connection (I1 burn-down
    # state is per-connection, so it dies with the connection).
    from aughor.semantic import ambiguity_ledger
    return {"ambiguity_resolutions": ambiguity_ledger.purge_connections([conn_id], org_id=org_id)}


def _overlay_conn(conn_id, org_id):
    # Wave K3: human overlay edits are per-connection annotations over that connection's data,
    # so they die with the connection.
    from aughor.kinetic import overlay
    return {"overlay_edits": overlay.purge_connections([conn_id], org_id=org_id)}


def _qdrant_conn(conn_id, org_id):
    # The connection's cached investigations + SQL examples (vector points keyed by
    # connection_id). The connection-KB collection is handled by connection_kb.
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from aughor.semantic.vector_store import delete_by_filter
    from aughor.tools.prior_analyses import (
        INVESTIGATIONS_COLLECTION,
        SQL_EXAMPLES_COLLECTION,
    )
    filt = Filter(must=[FieldCondition(key="connection_id", match=MatchValue(value=conn_id))])
    total = 0
    for coll in (INVESTIGATIONS_COLLECTION, SQL_EXAMPLES_COLLECTION):
        total += delete_by_filter(coll, filt) or 0
    return {"qdrant_points": total}


# schema-keyed hooks ----------------------------------------------------------

def _profile_schema(conn_id, schema):
    from aughor.profile import store as profile_store
    profile_store.invalidate(conn_id, schema)
    return {"profile": 1}


def _ontology_schema(conn_id, schema):
    from aughor.ontology import store as ontology_store
    ontology_store.invalidate(conn_id, schema)
    return {"ontology": 1}


def _knowledge_schema(conn_id, schema):
    # briefing is schema-scoped; patterns is connection-level (stale once any schema goes).
    from aughor.knowledge import briefing, patterns
    return {"briefing_cache": briefing.invalidate(conn_id, schema),
            "patterns_cache": patterns.invalidate(conn_id)}


def _watermark_schema(conn_id, schema):
    from aughor.explorer import watermark
    return {"watermark": watermark.clear_schema(conn_id, schema)}


def _packs_schema(conn_id, schema):
    from aughor.packs import bindings
    return {"pack_bindings": bindings.purge_schema(conn_id, schema)}


def _profile_cache_schema(conn_id, schema):
    from aughor.tools import profile_cache
    profile_cache.invalidate(conn_id)
    return {"profile_cache": 1}


def _monitors_schema(conn_id, schema):
    from aughor.monitors import store as monitor_store
    return {"monitors": monitor_store.purge_schema(conn_id, schema)}


# investigation-keyed hooks ---------------------------------------------------

def _evidence_inv(inv_ids):
    from aughor.evidence import store as evidence_store
    return {"evidence_claims": evidence_store.purge_investigations(inv_ids)}


def _qdrant_inv(inv_ids):
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from aughor.semantic.vector_store import delete_by_filter
    from aughor.tools.prior_analyses import INVESTIGATIONS_COLLECTION
    total = 0
    for inv_id in inv_ids:
        filt = Filter(must=[FieldCondition(key="inv_id", match=MatchValue(value=inv_id))])
        total += delete_by_filter(INVESTIGATIONS_COLLECTION, filt) or 0
    return {"qdrant_points": total}
