"""Canonical metric resolver — ONE source of truth for "what is metric X's formula".

Reconciles the two metric stores so a concept like "revenue" resolves to the SAME SQL
in both the /chat and the Deep-Analysis (ADA) paths — the "revenue means two different
things" class of bug:

  • data/metrics.json (MetricDefinition)        — human-curated, highest authority
  • the ontology's OntologyMetric.formula_sql   — LLM-enriched, gated by M24c verification

Precedence (highest first): curated catalog > verified ontology > unverified ontology.
Dedup is by normalized metric name. This is the primitive the NL2SQL semantic compiler
will read from (see STUDY_NL2SQL_ADVISORY_JUXTAPOSED.md — "canonical formulas live in two
stores that must reconcile"). It is deterministic and side-effect-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Higher rank wins when the same metric name appears in more than one store.
# profile_governed = the connection's BusinessProfile north-star metrics: build-time
# audited, connection-specific governed SQL — above the ontology, below the human catalog.
_SOURCE_RANK = {"catalog": 4, "profile_governed": 3, "ontology_verified": 2, "ontology_unverified": 1}


@dataclass
class CanonicalMetric:
    name: str
    label: str
    sql: str
    unit: str = ""
    tables: list = field(default_factory=list)
    source: str = "catalog"          # catalog | ontology_verified | ontology_unverified
    verified: bool = True            # curated + M24c-verified are trustworthy for injection
    caveats: str = ""

    @property
    def rank(self) -> int:
        return _SOURCE_RANK.get(self.source, 0)


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_").replace("-", "_")


def resolve_canonical_metrics(
    connection_id: str = "",
    schema_name: Optional[str] = None,
    *,
    catalog=None,
    ontology=None,
    schema_text: Optional[str] = None,
) -> list[CanonicalMetric]:
    """Merge the catalog + ontology metric stores into one deduplicated, precedence-ranked
    list (sorted by name). ``catalog`` (iterable of MetricDefinition) and ``ontology``
    (an OntologyGraph) are injectable for testing; otherwise loaded live and best-effort.

    ``schema_text`` lets a caller that ALREADY holds the connection's schema pass it in,
    so the catalog schema-filter below doesn't re-introspect it. That re-introspection was
    the dominant per-investigation latency cost on big warehouses (a 75k-schema fetch took
    ~17s, paid on EVERY call, duplicating the schema the caller had already cached).
    """
    by_name: dict[str, CanonicalMetric] = {}

    def _consider(m: CanonicalMetric) -> None:
        key = _norm(m.name)
        if not key or not (m.sql or "").strip():
            return
        cur = by_name.get(key)
        if cur is None or m.rank > cur.rank:
            by_name[key] = m

    # 1. Curated catalog (data/metrics.json) — highest authority.
    if catalog is None:
        try:
            from aughor.semantic.metrics import list_metrics
            catalog = list_metrics()
        except Exception:
            catalog = []

    # Metrics are GLOBAL. Filter the catalog to the target schema by table+column
    # existence so one connection's metric can't pollute another's prompt (the
    # #2 leak class: a curated revenue=SUM(total_amount) metric must NOT inject
    # into TPC-H, whose orders table has o_totalprice, not total_amount).
    catalog = list(catalog or [])
    if catalog and connection_id:
        _schema_text = schema_text or ""
        if not _schema_text:
            _db = None
            try:
                from aughor.db.connection import open_connection_for
                _db = open_connection_for(connection_id)
                _schema_text = _db.get_schema()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "metric schema-filter is best-effort; unfiltered catalog "
                         "is safe (over-injection, not wrong injection)",
                         counter="metrics.schema_filter", conn_id=connection_id)
            finally:
                # Release back to the pool. open_connection_for hands out a POOLED
                # connection whose .close() is swapped to a pool-RELEASE (not a physical
                # close); skipping it leaks the checkout. The latency win comes from
                # avoiding this fetch entirely when schema_text is passed, not from here.
                if _db is not None:
                    try:
                        _db.close()
                    except Exception:
                        pass
        if _schema_text:
            from aughor.semantic.metrics import filter_metrics_to_schema
            catalog = filter_metrics_to_schema(catalog, _schema_text)

    for md in catalog or []:
        _consider(CanonicalMetric(
            name=getattr(md, "name", "") or "",
            label=getattr(md, "label", "") or getattr(md, "name", ""),
            sql=getattr(md, "sql", "") or "",
            unit=getattr(md, "unit", "") or "",
            tables=list(getattr(md, "tables", []) or []),
            source="catalog",
            verified=True,
            caveats=getattr(md, "caveats", "") or "",
        ))

    # 2. Ontology metrics — verified outrank unverified; both below the catalog.
    if ontology is None and connection_id:
        try:
            from aughor.ontology.store import load_latest_ontology
            ontology = load_latest_ontology(connection_id, schema_name)
        except Exception:
            ontology = None
    onto_metrics = (getattr(ontology, "metrics", {}) or {}).values() if ontology is not None else []
    for om in onto_metrics:
        verified = bool(getattr(om, "verified", False))
        _consider(CanonicalMetric(
            name=getattr(om, "id", "") or "",
            label=getattr(om, "display_name", "") or getattr(om, "id", ""),
            sql=getattr(om, "formula_sql", "") or "",
            unit=getattr(om, "unit", "") or "",
            tables=list(getattr(om, "tables", []) or []),
            source="ontology_verified" if verified else "ontology_unverified",
            verified=verified,
        ))

    # 3. BusinessProfile north-star metrics — the connection's GOVERNED, build-time-audited
    # formulas (the same value_sql the Briefing/KPI strip run). These are the source of
    # truth for connection-specific metrics like missimi's gross margin; injecting them is
    # what lets ADA BIND to the real formula instead of re-deriving (RC2). The full value_sql
    # (with its FROM/WHERE) is the most faithful reference — it also makes the absence of a
    # 'quantity' column explicit.
    if connection_id:
        try:
            from aughor.profile.store import load as _load_profile
            _prof = _load_profile(connection_id, schema_name)
            for nsm in (getattr(_prof, "north_star_metrics", None) or []):
                vsql = (getattr(nsm, "value_sql", "") or "").strip()
                if not vsql:
                    continue
                _consider(CanonicalMetric(
                    name=getattr(nsm, "name", "") or "",
                    label=getattr(nsm, "name", "") or "",
                    sql=vsql,
                    unit=getattr(nsm, "unit_or_range", "") or "",
                    source="profile_governed",
                    verified=True,
                    caveats=(getattr(nsm, "definition", "") or "")[:160],
                ))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "profile north-star injection is best-effort; catalog + ontology "
                     "metrics still resolve without it", counter="canonical.north_star")

    return sorted(by_name.values(), key=lambda m: m.name)


def render_canonical_metrics_block(metrics, *, include_unverified: bool = False) -> str:
    """Format resolved metrics as a prompt block. Unverified ontology formulas are
    excluded by default — they must never be injected as authoritative SQL. Returns "" when
    there's nothing trustworthy to inject (so callers can append unconditionally)."""
    usable = [m for m in metrics if (m.sql or "").strip() and (m.verified or include_unverified)]
    if not usable:
        return ""
    lines = ["CANONICAL METRICS — use these EXACT formulas; never re-derive a metric listed here:"]
    for m in usable:
        unit = f" [{m.unit}]" if m.unit else ""
        tag = "" if m.verified else " (unverified — use only if no verified form exists)"
        lines.append(f"  - {m.name}{unit} = {m.sql}{tag}")
        if m.caveats:
            lines.append(f"      caveat: {m.caveats}")
    return "\n".join(lines)


def canonical_metrics_block(connection_id: str = "", schema_name: Optional[str] = None,
                            schema_text: Optional[str] = None) -> str:
    """Convenience: resolve + render in one call (the form callers inject). No-op safe.
    Pass ``schema_text`` when the caller already holds the schema to avoid a costly
    re-introspection (see resolve_canonical_metrics)."""
    return render_canonical_metrics_block(
        resolve_canonical_metrics(connection_id, schema_name, schema_text=schema_text))


def unified_metric_grounding(connection_id: str = "", schema_name: Optional[str] = None,
                             schema_text: Optional[str] = None, question: str = "") -> str:
    """The SINGLE metric-grounding block BOTH NL2SQL paths inject, so a metric resolves to the
    SAME SQL in /chat AND Deep Analysis (the "revenue means two different things" / "Insight vs
    Deep disagree on the same metric" class). It is the UNION of the two blocks each path used
    to inject separately:

      • the GOVERNED catalog block (``build_metrics_block`` — data/metrics.json formulas with
        approval badges + NEVER-usage rules, schema-filtered, ontology-overlaid), and
      • the connection's NORTH-STAR + verified-ontology formulas (``resolve_canonical_metrics``
        minus the catalog rows already rendered above, so nothing is listed twice).

    /chat historically injected only the FIRST — so it never saw the build-time-audited
    north-star ``value_sql`` and re-derived gross margin / ROAS / AOV, free to disagree with
    Deep, which injected only the SECOND (and so missed the catalog's NEVER rules). Routing both
    paths through this one function gives each path BOTH halves. No-op safe; pass ``schema_text``
    to avoid a re-introspection."""
    parts: list[str] = []
    try:
        from aughor.semantic.metrics import build_metrics_block
        gov = build_metrics_block(schema_text=schema_text or "", connection_id=connection_id,
                                  question=question)
        if gov:
            parts.append(gov)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "unified grounding: governed-catalog block best-effort; "
                 "canonical metrics still inject", counter="canonical.unified_catalog")
    try:
        extra = [m for m in resolve_canonical_metrics(connection_id, schema_name, schema_text=schema_text)
                 if m.source != "catalog"]   # catalog already rendered above with its governance
        block = render_canonical_metrics_block(extra)
        if block:
            parts.append(block)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "unified grounding: canonical block best-effort; governed catalog "
                 "still injects", counter="canonical.unified_canonical")
    return "\n\n".join(parts)
