"""Unit tests for the one governed-metric contract (REC-U10) — `aughor/semantic/contracts.py`.

The two metric shapes (curated `MetricDefinition`, ontology-derived `OntologyMetric`) both
serialize to `SemanticContract` with the fields planning/enforcement/display rely on, and
each source's trust signal (governance approval / live verification) maps to `is_trusted`.
"""
from __future__ import annotations

from aughor.ontology.models import OntologyMetric
from aughor.profile.models import NorthStarMetric
from aughor.semantic.contracts import SemanticContract
from aughor.semantic.metrics import MetricDefinition


# ── MetricDefinition → contract ──────────────────────────────────────────────────────────

def test_from_metric_definition_maps_core_fields():
    md = MetricDefinition(
        name="mrr", label="Monthly Recurring Revenue",
        sql="SUM(amount) FILTER (WHERE status='active')",
        tables=["subscriptions"], dimensions=["plan"], filters=["is_test = false"],
        unit="$", caveats="excludes refunds", additivity="additive",
        target_value=100000.0, warning_threshold=90000.0, critical_threshold=80000.0,
        target_period="monthly", benchmark_source="internal: FY25",
        owner="Revenue team", wrong_usage_examples=["never average MRR across months"],
    )
    c = SemanticContract.from_metric_definition(md)
    assert c.source == "catalog"
    assert (c.key, c.label, c.sql) == ("mrr", "Monthly Recurring Revenue", md.sql)
    assert c.unit == "$" and c.additivity == "additive"
    assert c.tables == ["subscriptions"] and c.dimensions == ["plan"] and c.filters == ["is_test = false"]
    assert c.known_divergent_calculations == ["never average MRR across months"]
    # health-scorecard block carried verbatim
    assert (c.target_value, c.warning_threshold, c.critical_threshold) == (100000.0, 90000.0, 80000.0)
    assert c.grain is None                       # catalog carries no explicit grain


def test_metric_definition_approval_is_the_trust_signal():
    approved = MetricDefinition(name="m", label="M", sql="SUM(x)", approved_by="Finance")
    # _govern_defaults promotes an approved-by metric to status=approved/v1
    c = SemanticContract.from_metric_definition(approved)
    assert c.status == "approved" and c.version == 1
    assert c.verified is True and c.is_trusted is True

    draft = MetricDefinition(name="d", label="D", sql="SUM(x)")
    cd = SemanticContract.from_metric_definition(draft)
    assert cd.status == "draft" and cd.is_trusted is False


# ── OntologyMetric → contract ────────────────────────────────────────────────────────────

def test_from_ontology_metric_maps_core_fields():
    om = OntologyMetric(
        id="revenue", display_name="Revenue", description="gross booked revenue",
        entity="order", formula_sql="SUM(total)", grain="per order", unit="$",
        tables=["orders"], known_divergent_calculations=["net vs gross"],
        target_value=5.0, benchmark_source="industry: ecommerce",
        verified=True, verification_note="ran clean 2026-07",
    )
    c = SemanticContract.from_ontology_metric(om)
    assert c.source == "ontology"
    assert (c.key, c.label, c.sql) == ("revenue", "Revenue", "SUM(total)")
    assert c.description == "gross booked revenue"
    assert c.grain == "per order" and c.unit == "$"
    assert c.tables == ["orders"] and c.known_divergent_calculations == ["net vs gross"]
    assert c.benchmark_source == "industry: ecommerce"


def test_ontology_verification_is_the_trust_signal():
    verified = OntologyMetric(id="r", display_name="R", entity="e", formula_sql="SUM(x)", verified=True)
    c = SemanticContract.from_ontology_metric(verified)
    assert c.verified is True and c.status == "approved" and c.is_trusted is True

    unverified = OntologyMetric(id="u", display_name="U", entity="e", formula_sql="SUM(x)", verified=False)
    cu = SemanticContract.from_ontology_metric(unverified)
    assert cu.verified is False and cu.status == "draft" and cu.is_trusted is False


# ── Both sources agree on the shared shape ───────────────────────────────────────────────

def test_both_sources_produce_the_same_contract_type_and_key_fields():
    md = MetricDefinition(name="aov", label="AOV", sql="AVG(total)", unit="$", tables=["orders"])
    om = OntologyMetric(id="aov", display_name="AOV", entity="order", formula_sql="AVG(total)",
                        unit="$", tables=["orders"])
    cm = SemanticContract.from_metric_definition(md)
    co = SemanticContract.from_ontology_metric(om)
    assert type(cm) is type(co) is SemanticContract
    # The durable identity + computation fields agree regardless of provenance.
    assert (cm.key, cm.label, cm.sql, cm.unit, cm.tables) == (co.key, co.label, co.sql, co.unit, co.tables)
    assert {cm.source, co.source} == {"catalog", "ontology"}


# ── NorthStarMetric → contract (the third governed-metric store) ──────────────────────────

def test_from_north_star_metric_maps_governed_fields():
    nsm = NorthStarMetric(
        name="gross_margin", definition="revenue minus COGS over revenue",
        maps_to="order_items.price, order_items.cost", why_it_matters="profitability signal",
        unit_or_range="percent 0-100",
        value_sql="SUM(price - cost) / NULLIF(SUM(price), 0)",
    )
    c = SemanticContract.from_north_star_metric(nsm)
    assert c.source == "profile"
    assert (c.key, c.label, c.sql) == ("gross_margin", "gross_margin", nsm.value_sql)
    assert c.unit == "percent 0-100"
    assert c.caveats == "revenue minus COGS over revenue"
    # Governed by provenance: build-time audited → trusted + injectable.
    assert c.status == "approved" and c.verified is True and c.is_trusted is True and c.injectable is True


# ── Precedence rank — the one dedup authority ────────────────────────────────────────────

def test_rank_orders_the_three_stores_catalog_first():
    catalog = SemanticContract.from_metric_definition(
        MetricDefinition(name="m", label="M", sql="SUM(x)"))
    profile = SemanticContract.from_north_star_metric(
        NorthStarMetric(name="m", definition="d", maps_to="t.c", why_it_matters="w",
                        unit_or_range="$", value_sql="SUM(y)"))
    onto_ok = SemanticContract.from_ontology_metric(
        OntologyMetric(id="m", display_name="M", entity="e", formula_sql="SUM(z)", verified=True))
    onto_no = SemanticContract.from_ontology_metric(
        OntologyMetric(id="m", display_name="M", entity="e", formula_sql="SUM(w)", verified=False))
    assert (catalog.rank, profile.rank, onto_ok.rank, onto_no.rank) == (4, 3, 2, 1)
    # Mirrors the legacy canonical._SOURCE_RANK exactly.
    from aughor.semantic.canonical import _SOURCE_RANK
    assert (catalog.rank, profile.rank, onto_ok.rank, onto_no.rank) == (
        _SOURCE_RANK["catalog"], _SOURCE_RANK["profile_governed"],
        _SOURCE_RANK["ontology_verified"], _SOURCE_RANK["ontology_unverified"])


# ── Injectable — the render-authority signal, byte-for-byte legacy CanonicalMetric.verified ─

def test_injectable_matches_legacy_render_policy():
    # catalog + profile are authoritative by provenance, even a draft catalog metric.
    draft_catalog = SemanticContract.from_metric_definition(MetricDefinition(name="d", label="D", sql="SUM(x)"))
    assert draft_catalog.is_trusted is False and draft_catalog.injectable is True
    profile = SemanticContract.from_north_star_metric(
        NorthStarMetric(name="p", definition="d", maps_to="t.c", why_it_matters="w",
                        unit_or_range="$", value_sql="SUM(y)"))
    assert profile.injectable is True
    # ontology is injectable only once self-verified.
    assert SemanticContract.from_ontology_metric(
        OntologyMetric(id="v", display_name="V", entity="e", formula_sql="SUM(z)", verified=True)).injectable is True
    assert SemanticContract.from_ontology_metric(
        OntologyMetric(id="u", display_name="U", entity="e", formula_sql="SUM(w)", verified=False)).injectable is False
