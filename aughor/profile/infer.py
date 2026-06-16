"""Infer a connection's Business/Industry Profile from its schema + glossary.

Leverages the model's world knowledge of how different industries operate, while
forcing every metric/question to be grounded in the ACTUAL columns present.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from aughor.profile.models import BusinessProfile
from aughor.profile import store

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a senior business+industry analyst. Given a database schema (tables, "
    "columns, types, row counts) with glossary annotations, determine what KIND of "
    "business this data represents and what matters for THAT specific industry.\n\n"
    "Use your knowledge of how different industries actually operate — e-commerce, "
    "airlines, SaaS, banking, healthcare, logistics, manufacturing, media, etc. An "
    "airline cares about load factor, on-time performance, fleet utilization and "
    "ancillary revenue; an e-commerce retailer cares about AOV, repeat-purchase rate, "
    "contribution margin and inventory turnover. The metrics that matter are "
    "industry-specific — name the ones that matter for THIS one.\n\n"
    "HARD RULES:\n"
    "1. Ground EVERY metric and question in the REAL tables/columns shown. Only "
    "propose metrics this data can actually compute; name the real columns in maps_to.\n"
    "2. For each metric, state its sane unit/range (unit_or_range) so downstream code "
    "can sanity-check results — e.g. a conversion rate is a ratio 0-1 (NEVER >1), a "
    "margin is a percent 0-100, revenue is USD at a human-readable magnitude.\n"
    "3. Be specific about the vertical (e.g. 'DTC Beauty E-commerce', not just 'Retail').\n"
    "4. key_questions are what a real analyst in this vertical asks on Monday morning, "
    "answerable from this data.\n"
    "5. For EVERY north-star metric you MUST also write value_sql: a runnable SELECT-only "
    "query that returns the metric's CURRENT value as a SINGLE scalar (one row, one numeric "
    "column with a readable alias), using only the real columns. Use correct grain — "
    "SUM(numerator)/NULLIF(SUM(denominator),0) for a rate, never AVG of a per-row ratio; "
    "a bounded rate must come out in its stated range. Do NOT leave value_sql empty."
)


def _gather_context(connection_id: str, schema_name: Optional[str]) -> tuple[str, list[str]]:
    """Return (glossary-enriched schema text, existing domain labels)."""
    from aughor.db.connection import open_connection_for
    from aughor.semantic.glossary import apply_glossary

    db = open_connection_for(connection_id)
    schema = db.get_schema()
    try:
        schema = apply_glossary(schema)
    except Exception as exc:
        logger.debug("apply_glossary failed (non-fatal): %s", exc)

    domains: list[str] = []
    try:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(connection_id, schema_name or None)
        if graph is not None:
            domains = sorted({e.domain for e in graph.entities.values() if getattr(e, "domain", None)})
    except Exception as exc:
        logger.debug("ontology domain hint unavailable (non-fatal): %s", exc)
    return schema, domains


def infer_business_profile(connection_id: str,
                           schema_name: Optional[str] = None) -> BusinessProfile:
    """Infer + persist the profile. Raises on connection/LLM failure."""
    from aughor.llm.provider import get_provider

    schema, domains = _gather_context(connection_id, schema_name)
    user = (
        "SCHEMA (tables, columns, types, row counts; with business glossary notes):\n"
        f"{schema}\n\n"
        f"GENERIC DOMAINS already assigned (for reference, may be too generic): {domains or 'none'}\n\n"
        "Identify the industry/vertical and business model, then list the 6-8 metrics "
        "and 6-8 questions that matter MOST for this specific business — each grounded "
        "in the real columns above."
    )
    llm = get_provider("coder")
    profile: BusinessProfile = llm.complete(
        system=_SYSTEM, user=user, response_model=BusinessProfile, temperature=0.2,
    )
    # Resolve each metric to a computation recipe (curated industry KB + LLM
    # fallback) HERE — at build time, not in the hot Phase-8 loop — so the explorer
    # just reads them. This is the SQL-accuracy knowledge (formula + grain + anti-
    # patterns). Best-effort: failure leaves recipes empty, profile still saved.
    recipes: list = []
    try:
        from aughor.profile import metric_kb
        recipes = metric_kb.resolve_recipes(profile, schema)
    except Exception as exc:
        logger.warning("[profile:%s] recipe resolution failed (non-fatal): %s", connection_id, exc)

    # Audit each metric's value_sql through the SAME grain/join guards the explorer
    # uses, plus a live range/boundary check (a bounded rate that exceeds its bound
    # or rounds to a boundary is a grain artifact). A failing value_sql is BLANKED so
    # the Briefing shows nothing rather than a wrong KPI. Then, for any metric we
    # blanked that HAS a curated recipe, regenerate its value_sql FROM the recipe's
    # canonical formula+grain (the recipe is the SQL-accuracy authority) and re-audit
    # — turning "drop the wrong number" into "show the right one" where we can.
    try:
        from aughor.profile.validate import audit_profile
        from aughor.db.connection import open_connection_for
        _conn = open_connection_for(connection_id)
        failed = audit_profile(profile, _conn, schema)
        if failed:
            logger.info("[profile:%s] value_sql audit dropped %d metric(s): %s",
                        connection_id, len(failed), failed)
            repaired = _regenerate_value_sql(profile, recipes, schema, _conn, set(failed))
            if repaired:
                logger.info("[profile:%s] recipe-grounded regeneration recovered %d metric(s): %s",
                            connection_id, len(repaired), sorted(repaired))
    except Exception as exc:
        logger.warning("[profile:%s] value_sql audit failed (non-fatal): %s", connection_id, exc)

    store.save(
        connection_id, profile,
        schema_name=schema_name,
        model=getattr(llm, "_model", None),
        generated_at=datetime.now(timezone.utc).isoformat(),
        recipes=recipes,
    )
    logger.info(
        "[profile:%s] inferred industry=%r model=%r — %d metrics, %d questions, %d recipes (conf=%.2f)",
        connection_id, profile.industry, profile.business_model,
        len(profile.north_star_metrics), len(profile.key_questions), len(recipes), profile.confidence,
    )
    return profile


def _norm_name(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _regenerate_value_sql(profile, recipes: list, schema: str, conn, only: set) -> set:
    """For each blanked metric in `only` that has a curated/LLM recipe, generate a
    fresh value_sql FROM the recipe's canonical formula+grain+anti_patterns (not the
    LLM's free-form first draft), then RE-AUDIT it through the same guards. Sets the
    metric's value_sql in place and returns the set of metric names actually
    recovered. Best-effort: one batched LLM call; failure leaves the metrics blank.

    This is the root-cause fix for the conversion=100% class of bug: the recipe
    says the denominator is COUNT(DISTINCT cart_id) over ALL carts, so the
    regenerated SQL can't fall into the `WHERE abandoned = 0` denominator trap the
    free-form draft did."""
    from aughor.profile.validate import audit_value_sql
    from aughor.tools.schema import _parse_schema_tables

    by_name = {_norm_name(r.get("metric", "")): r for r in (recipes or []) if r.get("formula")}
    targets = []  # (metric_obj, recipe)
    for m in getattr(profile, "north_star_metrics", []) or []:
        if m.name in only:
            r = by_name.get(_norm_name(m.name))
            if r:
                targets.append((m, r))
    if not targets:
        return set()

    from pydantic import BaseModel, Field

    class _MetricSql(BaseModel):
        name: str = Field(description="The metric name, copied EXACTLY from the request")
        value_sql: str = Field(description="A runnable SELECT-only scalar query (one row, one numeric column)")

    class _Out(BaseModel):
        metrics: list[_MetricSql]

    spec = "\n\n".join(
        f"METRIC: {m.name}\n"
        f"  maps_to: {m.maps_to}\n"
        f"  unit/range: {m.unit_or_range}\n"
        f"  canonical formula: {r.get('formula')}\n"
        f"  grain (compute at this grain): {r.get('grain')}\n"
        f"  AVOID: {' | '.join(r.get('anti_patterns', []) or [])}"
        for m, r in targets
    )
    system = (
        "You are a precise analytics engineer. For each metric, write value_sql: a "
        "runnable DuckDB SELECT-only query returning the metric's CURRENT value as a "
        "SINGLE scalar (one row, one numeric column with a readable alias). You MUST "
        "follow the metric's canonical FORMULA and GRAIN exactly and AVOID the listed "
        "anti-patterns. Use only real tables/columns from the schema. A bounded rate "
        "(0..1 or 0..100%) MUST be computed so its denominator is the FULL population "
        "(e.g. ALL carts, not just converted ones) — never filter the denominator down "
        "to the success condition. Pre-aggregate each side of a multi-table join to the "
        "shared key in its own CTE before joining (avoid fan-out over-counting)."
    )
    user = f"SCHEMA:\n{schema}\n\nWrite value_sql for EACH metric below:\n\n{spec}"

    from aughor.llm.provider import get_provider
    llm = get_provider("coder")
    try:
        out: _Out = llm.complete(system=system, user=user, response_model=_Out, temperature=0.0)
    except Exception as exc:
        logger.warning("[profile] value_sql regeneration LLM call failed (non-fatal): %s", exc)
        return set()

    table_cols = {}
    try:
        table_cols = _parse_schema_tables(schema)
    except Exception:
        pass
    fresh = {_norm_name(x.name): (x.value_sql or "").strip() for x in out.metrics}
    recovered: set = set()
    for m, _r in targets:
        cand = fresh.get(_norm_name(m.name), "")
        if not cand:
            continue
        ok, reason = audit_value_sql(cand, table_cols, conn, m.unit_or_range)
        if ok:
            m.value_sql = cand
            recovered.add(m.name)
        else:
            logger.info("[profile] regenerated value_sql for %r still failed audit: %s", m.name, reason)
    return recovered


def get_or_infer(connection_id: str,
                 schema_name: Optional[str] = None) -> Optional[BusinessProfile]:
    """Cached profile if present; else infer once. Best-effort — None on failure
    so callers (e.g. the explorer) degrade gracefully to generic behavior."""
    cached = store.load(connection_id)
    if cached is not None:
        return cached
    try:
        return infer_business_profile(connection_id, schema_name)
    except Exception as exc:
        logger.warning("[profile:%s] inference failed (degrading to generic): %s",
                       connection_id, exc)
        return None
