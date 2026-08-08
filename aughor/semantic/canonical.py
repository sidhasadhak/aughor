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

from typing import Optional


# Higher rank wins when the same metric name appears in more than one store.
# profile_governed = the connection's BusinessProfile north-star metrics: build-time
# audited, connection-specific governed SQL — above the ontology, below the human catalog.
# _SOURCE_RANK / _norm left with the CanonicalMetric resolver (2026-08-06);
# `contracts.py` carries the authoritative rank + key-normalization mirrors.


# ── Source loaders — the three governed-metric stores, loaded once and shared by BOTH the
#    CanonicalMetric resolver and the contract-native resolver (REC-U10). Extracting them here
#    is what lets the two resolvers stay in lockstep instead of drifting: they consume the same
#    raw source models and differ only in the (cheap) mapping to their target type. ─────────────

def _load_catalog_metrics(connection_id: str, schema_text: Optional[str], catalog) -> list:
    """Curated catalog (data/metrics.json) — highest authority, schema-filtered.

    ``catalog`` is injectable for testing; otherwise loaded live and best-effort. Metrics are
    GLOBAL, so filter to the target schema by table+column existence — one connection's curated
    ``revenue=SUM(total_amount)`` must NOT inject into TPC-H (whose orders table has
    ``o_totalprice``, not ``total_amount``). ``schema_text`` lets a caller that already holds the
    schema pass it in, avoiding a re-introspection (the dominant per-investigation latency cost —
    a 75k-schema fetch took ~17s, paid on EVERY call)."""
    if catalog is None:
        try:
            from aughor.semantic.metrics import list_metrics
            catalog = list_metrics()
        except Exception:
            catalog = []
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
    return list(catalog or [])


def _load_ontology_metrics(connection_id: str, schema_name: Optional[str], ontology) -> list:
    """The ontology's metrics (LLM-enriched, gated by M24c verification). ``ontology`` (an
    OntologyGraph) is injectable for testing; otherwise loaded live and best-effort."""
    if ontology is None and connection_id:
        try:
            from aughor.ontology.store import load_latest_ontology
            ontology = load_latest_ontology(connection_id, schema_name)
        except Exception:
            ontology = None
    return list((getattr(ontology, "metrics", {}) or {}).values()) if ontology is not None else []


def _load_profile_north_stars(connection_id: str, schema_name: Optional[str]) -> list:
    """The connection's GOVERNED, build-time-audited north-star metrics (the same value_sql the
    Briefing/KPI strip run). These are the source of truth for connection-specific metrics like
    missimi's gross margin; injecting them is what lets ADA BIND to the real formula instead of
    re-deriving (RC2). Best-effort — a missing profile just drops this source."""
    if not connection_id:
        return []
    try:
        from aughor.business_profile.store import load as _load_profile
        _prof = _load_profile(connection_id, schema_name)
        return list(getattr(_prof, "north_star_metrics", None) or [])
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "profile north-star injection is best-effort; catalog + ontology "
                 "metrics still resolve without it", counter="canonical.north_star")
        return []


# `resolve_canonical_metrics` was DELETED by flag endgame Wave 2 (2026-08-06) —
# the `semantic.contract_live` migration completed its obligation: the planning
# path resolves through `resolve_planning_metrics` (SemanticContract behind
# `_ContractMetricView`, proven byte-identical, receipt e801ff3a4448), and the
# CanonicalMetric shape left with its resolver.

def resolve_contracts(
    connection_id: str = "",
    schema_name: Optional[str] = None,
    *,
    catalog=None,
    ontology=None,
    schema_text: Optional[str] = None,
) -> list:
    """The contract-native twin of ``resolve_canonical_metrics`` (REC-U10): resolve the SAME
    three governed-metric stores into one deduped, precedence-ranked ``list[SemanticContract]`` —
    the one type planning/enforcement/display point at. Precedence (highest first): curated
    catalog > profile-governed > verified ontology > unverified ontology, deduped by normalized
    key. Shares the source loaders (so it can't drift from the canonical resolver) but carries the
    FULL contract — thresholds, additivity, divergence rules — that the ``CanonicalMetric`` shape
    dropped. Fail-open per entry; never raises."""
    from aughor.kernel.errors import tolerate
    from aughor.semantic.contracts import SemanticContract, dedup_by_rank

    out: list = []
    for md in _load_catalog_metrics(connection_id, schema_text, catalog):
        try:
            out.append(SemanticContract.from_metric_definition(md))
        except Exception as exc:
            tolerate(exc, "resolve_contracts: catalog metric skipped", counter="canonical.contracts")
    for om in _load_ontology_metrics(connection_id, schema_name, ontology):
        try:
            out.append(SemanticContract.from_ontology_metric(om))
        except Exception as exc:
            tolerate(exc, "resolve_contracts: ontology metric skipped", counter="canonical.contracts")
    for nsm in _load_profile_north_stars(connection_id, schema_name):
        try:
            out.append(SemanticContract.from_north_star_metric(nsm))
        except Exception as exc:
            tolerate(exc, "resolve_contracts: north-star metric skipped", counter="canonical.contracts")

    return dedup_by_rank(out)


def render_contracts_block(contracts, *, include_unverified: bool = False) -> str:
    """The contract-native twin of ``render_canonical_metrics_block`` — renders a
    ``list[SemanticContract]`` to the SAME prompt block, byte-for-byte. The render-authority
    signal is the contract's ``injectable`` property, which is defined to equal the legacy
    ``CanonicalMetric.verified`` exactly (catalog/profile authoritative by provenance; ontology
    only once self-verified), so a flag flip is a pure no-op on the emitted text. ``key`` fills
    the ``name`` slot (they're the same identifier from each source)."""
    usable = [c for c in contracts if (c.sql or "").strip() and (c.injectable or include_unverified)]
    if not usable:
        return ""
    lines = ["CANONICAL METRICS — use these EXACT formulas; never re-derive a metric listed here:"]
    for c in usable:
        unit = f" [{c.unit}]" if c.unit else ""
        tag = "" if c.injectable else " (unverified — use only if no verified form exists)"
        lines.append(f"  - {c.key}{unit} = {c.sql}{tag}")
        if c.caveats:
            lines.append(f"      caveat: {c.caveats}")
    return "\n".join(lines)


class _ContractMetricView:
    """Adapts a ``SemanticContract`` to the exact attribute shape the semantic compiler reads
    (``name``/``verified``/``sql``/``tables``/``label``/``unit``/``source``). ``verified`` maps to
    the contract's ``injectable`` property — which is DEFINED equal to the legacy
    ``CanonicalMetric.verified`` trust/render policy byte-for-byte (catalog + profile authoritative
    by provenance; ontology only once self-verified) — so repointing the compiler at the one
    ``SemanticContract`` is a pure no-op on the SQL it synthesizes (REC-U10 tail)."""

    __slots__ = ("_c",)

    def __init__(self, contract) -> None:
        self._c = contract

    @property
    def name(self) -> str:
        return self._c.key

    @property
    def label(self) -> str:
        return self._c.label

    @property
    def sql(self) -> str:
        return self._c.sql

    @property
    def unit(self) -> str:
        return self._c.unit or ""

    @property
    def tables(self) -> list:
        return self._c.tables

    @property
    def source(self) -> str:
        return self._c.source

    @property
    def verified(self) -> bool:
        return self._c.injectable

    @property
    def rank(self) -> int:
        # The matcher's precedence tiebreak (`_match_canonical_metric` reads
        # `getattr(m, "rank", 0)` — a fail-open that would have SILENTLY flattened
        # catalog-over-ontology precedence at match time had the view not carried
        # it; caught by the PR-2 adversarial self-review, not by any test).
        return self._c.rank


def resolve_planning_metrics(
    connection_id: str = "",
    schema_name: Optional[str] = None,
    *,
    catalog=None,
    ontology=None,
    schema_text: Optional[str] = None,
) -> list:
    """STRUCTURED metric resolver for the planning path (REC-U10 — ``CanonicalMetric``
    retired). The three governed stores resolve into ``SemanticContract``s presented
    through ``_ContractMetricView``, so consumers read one contract type in the exact
    attribute shape the legacy list carried; ``verified`` maps to the contract's
    ``injectable`` (defined equal to the legacy field), so synthesized SQL is
    unchanged. The legacy branch was deleted by flag endgame Wave 2 (2026-08-06)
    after the flip soaked default-ON from 2026-07-31 (receipt e801ff3a4448)."""
    return [
        _ContractMetricView(c)
        for c in resolve_contracts(
            connection_id, schema_name, catalog=catalog, ontology=ontology,
            schema_text=schema_text)
    ]


def canonical_metrics_block(connection_id: str = "", schema_name: Optional[str] = None,
                            schema_text: Optional[str] = None) -> str:
    """Convenience: resolve + render in one call (the form callers inject). No-op safe.
    Pass ``schema_text`` when the caller already holds the schema to avoid a costly
    re-introspection (see resolve_contracts). Renders from the unified
    SemanticContract — the one metric type (REC-U10; legacy path deleted 2026-08-06)."""
    return render_contracts_block(
        resolve_contracts(connection_id, schema_name, schema_text=schema_text))


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
        # catalog already rendered above (build_metrics_block) with its governance — so this half
        # renders only the north-star + ontology formulas, from the unified
        # SemanticContract (REC-U10; the CanonicalMetric twin was deleted 2026-08-06).
        extra = [c for c in resolve_contracts(connection_id, schema_name, schema_text=schema_text)
                 if c.source != "catalog"]
        block = render_contracts_block(extra)
        if block:
            parts.append(block)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "unified grounding: canonical block best-effort; governed catalog "
                 "still injects", counter="canonical.unified_canonical")
    return "\n\n".join(parts)
