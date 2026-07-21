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
    "3. Be specific about the vertical (e.g. 'DTC Beauty E-commerce', not just 'Retail'), "
    "and classify by the DOMINANT data — the tables with the most rows / the bulk of "
    "revenue — NOT a minority subsystem. If most orders and revenue are apparel/electronics "
    "but a few small tables describe a bakery, it is multi-category retail, not a bakery.\n"
    "4. key_questions are what a real analyst in this vertical asks on Monday morning, "
    "answerable from this data. Include at LEAST ONE composite question that ANDs two "
    "metrics on a SHARED entity (e.g. 'which categories/SKUs are BOTH high-margin AND "
    "high-return?') — the cross-domain question single-metric views miss.\n"
    "4b. business_model must be EVIDENCE-CITED like maps_to: do NOT claim 'subscription', "
    "'recurring', 'marketplace', 'freemium' or 'ad-supported' unless a real table/column "
    "supports it (a plan/renewal/billing-cycle table for subscription, a seller/listing "
    "table for marketplace). State the transactional model the columns actually show.\n"
    "5. For EVERY north-star metric you MUST also write value_sql: a runnable SELECT-only "
    "query that returns the metric's CURRENT value as a SINGLE scalar (one row, one numeric "
    "column with a readable alias), using only the real columns. Use correct grain — "
    "SUM(numerator)/NULLIF(SUM(denominator),0) for a rate, never AVG of a per-row ratio; "
    "a bounded rate must come out in its stated range. Do NOT leave value_sql empty.\n"
    "6. For EVERY north-star metric ALSO write chart_sql: a runnable SELECT-only query that "
    "EXPLAINS the metric as a small SERIES (NOT a scalar) — a time TREND (date_trunc the "
    "natural date to day/week, metric per bucket, ORDER BY bucket) for a flow/rate metric "
    "(AOV, gross margin), or a TOP-N BREAKDOWN (metric by category, ORDER BY metric DESC "
    "LIMIT 5-10) for a composition metric (top return reasons, revenue by channel). Two "
    "columns, ≥2 rows, same correct grain as value_sql."
)


# A business-model claim is only credible if the schema carries a supporting artifact.
# (Conservative set — only the claims we've seen hallucinated, with strong evidence tokens.)
_MODEL_CLAIM_EVIDENCE = {
    "subscription": ("subscription", "plan_id", "plan_name", "renewal", "billing_cycle", "mrr", "subscriber"),
    "recurring":    ("subscription", "renewal", "recurring", "mrr", "billing_cycle"),
    "marketplace":  ("seller", "vendor_id", "listing", "merchant", "commission", "take_rate"),
}


def _strip_unsupported_model(profile, schema: str) -> None:
    """F7 — drop business_model clauses the schema can't support (the hallucinated
    'subscription' on a one-time-purchase warehouse). Mutates profile in place; best-effort."""
    import re as _re
    try:
        bm = (getattr(profile, "business_model", "") or "")
        low_schema = schema.lower()
        for claim, evidence in _MODEL_CLAIM_EVIDENCE.items():
            if _re.search(rf"\b{claim}\b", bm, _re.IGNORECASE) and not any(e in low_schema for e in evidence):
                bm = _re.sub(rf"\b{claim}\b", "", bm, flags=_re.IGNORECASE)
        # tidy dangling connectors/punctuation left by removal
        bm = _re.sub(r"\s*[&,/]\s*(?=[&,/]|$)", " ", bm)
        bm = _re.sub(r"^\s*[&,/\-]\s*|\s*[&,/\-]\s*$", "", bm)
        bm = _re.sub(r"\s{2,}", " ", bm).strip(" -&,/")
        if bm:
            profile.business_model = bm
    except Exception as exc:
        logger.debug("[profile] business_model grounding skipped: %s", exc)


_COMPOSITE_RE = __import__("re").compile(r"\bboth\b|high.*\band\b.*high|\band\b.*(rate|margin|return)", __import__("re").IGNORECASE)
_MARGINY = ("margin", "profit")
_RETURNY = ("return", "refund")


def _ensure_composite_question(profile) -> None:
    """F5 — guarantee at least one cross-domain AND question (the margin-leak class a
    single-metric view misses). If the LLM didn't produce one, synthesize it from a
    margin metric + a return metric when both exist. Mutates profile in place."""
    try:
        qs = list(getattr(profile, "key_questions", None) or [])
        if any(_COMPOSITE_RE.search(q) for q in qs):
            return
        names = " ".join((m.name or "").lower() for m in (getattr(profile, "north_star_metrics", None) or []))
        if any(t in names for t in _MARGINY) and any(t in names for t in _RETURNY):
            qs.append("Which product categories (or SKUs) are BOTH high-margin AND high-return — "
                      "the profit that returns erode most?")
            profile.key_questions = qs
    except Exception as exc:
        logger.debug("[profile] composite-question seed skipped: %s", exc)


def _calibrate_ranges(profile, conn) -> None:
    """F4 — anchor each metric's sane band on the MEASURED value instead of a guess. The
    LLM guesses 'USD (human scale: 20-150)' from world knowledge; if the real AOV is $537
    a downstream magnitude check would flag the CORRECT value as anomalous. Run each green
    value_sql once, append '(measured ≈ X)' so the band reflects this dataset. Keeps the
    KIND (ratio/pct/usd) from world knowledge — only the magnitude is data-anchored.
    Best-effort, mutates in place."""
    def _as_num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    for m in (getattr(profile, "north_star_metrics", None) or []):
        sql = (getattr(m, "value_sql", "") or "").strip()
        if not sql or "measured" in (m.unit_or_range or "").lower():
            continue
        try:
            res = conn.execute("profile-calibrate", sql)
            rows = (getattr(res, "rows", None) or []) if not getattr(res, "error", None) else []
            val = next((n for n in (_as_num(c) for c in (rows[0] if rows else [])) if n is not None), None)
            if val is not None:
                mag = f"{val:,.2f}".rstrip("0").rstrip(".")
                m.unit_or_range = f"{(m.unit_or_range or '').strip()} (measured ≈ {mag})".strip()
        except Exception as exc:
            logger.debug("[profile] range calibration skipped for %s: %s", getattr(m, "name", "?"), exc)


def _gather_context(connection_id: str, schema_name: Optional[str]) -> tuple[str, list[str]]:
    """Return (glossary-enriched schema text, existing domain labels)."""
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema
    from aughor.semantic.glossary import apply_glossary

    # Scope to the requested schema so a per-schema profile is inferred from ONLY that
    # schema's tables — otherwise a multi-schema connection's get_schema() returns every
    # table and the largest schema dominates (e.g. every schema getting a "Missimi-focused"
    # profile). None → connection-level (unchanged for single-schema connections).
    db = (open_connection_for_with_schema(connection_id, schema_name)
          if schema_name else open_connection_for(connection_id))
    schema = db.get_schema()
    try:
        schema = apply_glossary(schema, schema=schema_name)   # scoped: see semantic.glossary.lookup_table
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
    # Declared identity (company/website/HQ/industry) grounds the inference in the REAL business,
    # not just the schema shape — e.g. a user-declared "Food Delivery" industry steers the
    # vertical/metric choices. '' when unset (no-op); the org override still wins at read time.
    org = ""
    try:
        from aughor.orgsettings import org_context
        org = org_context()
    except Exception as _e:
        logger.debug("[profile:%s] org_context unavailable: %s", connection_id, _e)
    user = (
        f"{org}"
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
    # Deterministic grounding guards (belt-and-suspenders to the prompt rules):
    _strip_unsupported_model(profile, schema)        # F7 — drop hallucinated "subscription" etc.
    _ensure_composite_question(profile)              # F5 — guarantee a cross-domain AND question
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
        from aughor.db.connection import open_connection_for, open_connection_for_with_schema
        _conn = (open_connection_for_with_schema(connection_id, schema_name)
                 if schema_name else open_connection_for(connection_id))
        failed = audit_profile(profile, _conn, schema)
        # Regenerate any metric (with a recipe) that lost EITHER its value_sql or its
        # chart_sql in the audit — recipe-grounded SQL is the SQL-accuracy authority.
        need_regen = {m.name for m in (profile.north_star_metrics or [])
                      if not (m.value_sql or "").strip() or not (m.chart_sql or "").strip()}
        if failed:
            logger.info("[profile:%s] value_sql audit dropped %d metric(s): %s",
                        connection_id, len(failed), failed)
        if need_regen:
            repaired = _regenerate_value_sql(profile, recipes, schema, _conn, need_regen)
            if repaired:
                logger.info("[profile:%s] recipe-grounded regeneration recovered SQL for %d metric(s): %s",
                            connection_id, len(repaired), sorted(repaired))
        _calibrate_ranges(profile, _conn)   # F4 — anchor sane bands on the MEASURED magnitude
    except Exception as exc:
        logger.warning("[profile:%s] value_sql audit failed (non-fatal): %s", connection_id, exc)

    # Build-time SQL for each key_question — generated ONCE here, with full schema +
    # recipe grounding and the composite-question rules, then audited. The explorer's
    # pinned pass runs these deterministically every run, so the hardest questions (the
    # SKU margin-leak: ">90% margin AND >10% returns") are answered REPRODUCIBLY instead
    # of depending on the hot loop's one-shot generation, which fails to bind them.
    try:
        from aughor.db.connection import open_connection_for as _open, open_connection_for_with_schema as _opens
        _kqconn = _opens(connection_id, schema_name) if schema_name else _open(connection_id)
        _generate_key_question_sql(profile, recipes, schema, _kqconn)
        _n = sum(1 for s in (profile.key_question_sql or []) if s.strip())
        logger.info("[profile:%s] generated %d/%d key-question SQLs", connection_id, _n,
                    len(profile.key_questions or []))
    except Exception as exc:
        logger.warning("[profile:%s] key-question SQL generation failed (non-fatal): %s", connection_id, exc)

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
    """For each blanked metric in `only` that has a curated/LLM recipe, generate fresh
    value_sql AND chart_sql FROM the recipe's canonical formula+grain+anti_patterns
    (not the LLM's free-form first draft), then RE-AUDIT each through the same guards.
    Sets whichever passes in place and returns the set of metric names where at least
    one was recovered. Best-effort: one batched LLM call; failure leaves blanks.

    Root-cause fix for the conversion=100% class of bug: the recipe says the
    denominator is COUNT(DISTINCT cart_id) over ALL carts, so the regenerated SQL
    can't fall into the `WHERE abandoned = 0` denominator trap the draft did — and the
    chart_sql explainer inherits the same correct grain."""
    from aughor.profile.validate import audit_value_sql, audit_chart_sql
    from aughor.tools.schema import parse_schema_tables

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
        chart_sql: str = Field(description="A runnable SELECT-only SERIES query (a trend or top-N breakdown; 2 cols, ≥2 rows)")

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
        "You are a precise analytics engineer. For each metric write TWO runnable DuckDB "
        "SELECT-only queries:\n"
        "• value_sql — the metric's CURRENT value as a SINGLE scalar (one row, one numeric "
        "column with a readable alias).\n"
        "• chart_sql — the metric as a small SERIES that EXPLAINS it: a time TREND "
        "(date_trunc the natural date to day/week/month, metric per bucket) for a "
        "flow/rate metric, or a TOP-N BREAKDOWN (metric by category, ORDER BY metric DESC "
        "LIMIT 5-10) for a composition metric. Two columns, ≥2 rows. For a time TREND that "
        "you LIMIT, order by the bucket DESCENDING (ORDER BY bucket DESC LIMIT N) so you get "
        "the MOST RECENT N periods — never `ORDER BY bucket LIMIT N` (ascending), which "
        "returns the OLDEST periods and freezes the chart on year-one of a multi-year "
        "dataset (the app re-sorts ascending for display).\n"
        "Both MUST follow the metric's canonical FORMULA and GRAIN exactly and AVOID the "
        "listed anti-patterns, using only real tables/columns from the schema. A bounded "
        "rate (0..1 or 0..100%) MUST keep its denominator the FULL population (e.g. ALL "
        "carts, not just converted ones) — never filter the denominator to the success "
        "condition. Pre-aggregate each side of a multi-table join to the shared key in its "
        "own CTE before joining (avoid fan-out over-counting)."
    )
    user = f"SCHEMA:\n{schema}\n\nWrite value_sql and chart_sql for EACH metric below:\n\n{spec}"

    from aughor.llm.provider import get_provider
    llm = get_provider("coder")
    try:
        out: _Out = llm.complete(system=system, user=user, response_model=_Out, temperature=0.0)
    except Exception as exc:
        logger.warning("[profile] value_sql regeneration LLM call failed (non-fatal): %s", exc)
        return set()

    table_cols = {}
    try:
        table_cols = parse_schema_tables(schema)
    except Exception:
        pass
    fresh = {_norm_name(x.name): x for x in out.metrics}
    recovered: set = set()
    for m, _r in targets:
        cand = fresh.get(_norm_name(m.name))
        if not cand:
            continue
        if not (m.value_sql or "").strip() and (cand.value_sql or "").strip():
            ok, reason = audit_value_sql(cand.value_sql.strip(), table_cols, conn, m.unit_or_range)
            if ok:
                m.value_sql = cand.value_sql.strip()
                recovered.add(m.name)
            else:
                logger.info("[profile] regenerated value_sql for %r still failed audit: %s", m.name, reason)
        if not (m.chart_sql or "").strip() and (cand.chart_sql or "").strip():
            ok, reason = audit_chart_sql(cand.chart_sql.strip(), table_cols, conn)
            if ok:
                m.chart_sql = cand.chart_sql.strip()
                recovered.add(m.name)
            else:
                logger.info("[profile] regenerated chart_sql for %r still failed audit: %s", m.name, reason)
    return recovered


def _generate_key_question_sql(profile, recipes: list, schema: str, conn) -> None:
    """Generate + audit build-time SQL for each of the profile's key_questions, in
    place into `profile.key_question_sql` (aligned by index; "" where none survives the
    audit). One batched LLM call with full schema + recipe + composite-question grounding,
    then a one-shot batched repair for the ones that fail to bind. Best-effort: any error
    leaves the list as-is. The build affords this care once so every run is deterministic."""
    from aughor.profile.validate import audit_finding_sql
    from aughor.tools.schema import parse_schema_tables
    from aughor.llm.provider import get_provider
    from pydantic import BaseModel, Field

    questions = [q for q in (getattr(profile, "key_questions", None) or []) if q.strip()]
    if not questions:
        profile.key_question_sql = []
        return
    try:
        table_cols = parse_schema_tables(schema)
    except Exception:
        table_cols = {}

    _rlines = ""
    for r in (recipes or [])[:8]:
        _aps = "; ".join((r.get("anti_patterns") or [])[:2])
        _rlines += f"  • {r.get('metric')}: formula={r.get('formula')}; grain={r.get('grain')}; AVOID={_aps}\n"

    system = (
        "You are a precise analytics engineer. For each numbered business question, write ONE "
        "runnable DuckDB SELECT that ANSWERS it using only real tables/columns from the schema. "
        "Rules: for a COMPOSITE question (two conditions on different metrics, e.g. high margin "
        "AND high return rate), compute EACH metric in its OWN CTE keyed by the entity, then JOIN "
        "the CTEs on the entity key and filter in the outer query — NEVER aggregate across a "
        "multi-table join directly (fan-out). Every rate = SUM(numerator)/NULLIF(SUM(denominator),0) "
        "at the correct grain (0..1, never >1). Follow the computation recipes. If a question truly "
        "cannot be answered from the schema, return an empty string for its sql."
    )

    class _QSql(BaseModel):
        index: int = Field(description="The question number, exactly as given")
        sql: str = Field(description="A runnable SELECT that answers it, or empty if impossible")

    class _Out(BaseModel):
        items: list[_QSql]

    def _ask(qs_with_idx: list[tuple[int, str]], note: str = "") -> dict[int, str]:
        spec = "\n".join(f"  [{i}] {q}" for i, q in qs_with_idx)
        user = f"SCHEMA:\n{schema}\n\nCOMPUTATION RECIPES:\n{_rlines}\n{note}\nQUESTIONS:\n{spec}"
        llm = get_provider("coder")
        out: _Out = llm.complete(system=system, user=user, response_model=_Out, temperature=0.0)
        return {it.index: (it.sql or "").strip() for it in out.items}

    result: list[str] = ["" for _ in questions]
    try:
        gen = _ask(list(enumerate(questions)))
    except Exception as exc:
        logger.warning("[profile] key-question SQL batch failed: %s", exc)
        gen = {}

    # Pass 1 (batched) collects the easy ones. Everything else — whether the batch
    # returned an EMPTY string (the model bailing via the "impossible" escape hatch on
    # a question that IS answerable — the dominant blank cause) or SQL that failed the
    # audit — goes to a PER-QUESTION retry. The old code `continue`d on empty, so the
    # bailed questions were never retried; a single batched repair shared the same
    # bail-prone format. Isolating each question (one job, no escape hatch) is what
    # actually recovers them.
    pending: list[tuple[int, str, str]] = []  # (index, question, why-it-needs-retry)
    for i, q in enumerate(questions):
        cand = gen.get(i, "")
        if not cand:
            pending.append((i, q, "the batch returned no SQL for it"))
            continue
        ok, reason = audit_finding_sql(cand, table_cols, conn)
        if ok:
            result[i] = cand
        else:
            pending.append((i, q, f"the first draft failed: {reason}"))

    # Pass 2: focused, single-question retries (≤2 attempts each). The model gets ONE
    # question, the prior failure reason, and an explicit no-bail instruction — these
    # questions were selected by the profiler BECAUSE the schema can answer them.
    for i, q, why in pending:
        for _attempt in range(2):
            note = (
                f"This is the ONLY question to answer. A previous attempt did not work: {why}. "
                "This question WAS selected because the schema CAN answer it — return a runnable "
                "SELECT, do NOT return an empty string. Pre-aggregate each metric in its own CTE "
                "keyed by the entity, use only columns that exist, and avoid fan-out.\n")
            try:
                cand = _ask([(i, q)], note=note).get(i, "")
            except Exception as exc:
                logger.info("[profile] key-question[%d] retry call failed: %s", i, exc)
                break
            if not cand:
                why = "the retry returned an empty string"
                continue
            ok, reason = audit_finding_sql(cand, table_cols, conn)
            if ok:
                result[i] = cand
                break
            why = f"the retry failed: {reason}"

    profile.key_question_sql = result
    n_empty = sum(1 for s in result if not s)
    if n_empty:
        logger.info("[profile] %d/%d key-question SQLs still empty after per-question retry",
                    n_empty, len(questions))


def get_or_infer(connection_id: str,
                 schema_name: Optional[str] = None) -> Optional[BusinessProfile]:
    """Cached profile if present; else infer once. Best-effort — None on failure
    so callers (e.g. the explorer) degrade gracefully to generic behavior."""
    cached = store.load(connection_id, schema_name)
    if cached is not None:
        return cached
    try:
        return infer_business_profile(connection_id, schema_name)
    except Exception as exc:
        logger.warning("[profile:%s] inference failed (degrading to generic): %s",
                       connection_id, exc)
        return None
