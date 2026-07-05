"""Unit tests for the one governed-metric contract (REC-U10) — `aughor/semantic/contracts.py`.

The two metric shapes (curated `MetricDefinition`, ontology-derived `OntologyMetric`) both
serialize to `SemanticContract` with the fields planning/enforcement/display rely on, and
each source's trust signal (governance approval / live verification) maps to `is_trusted`.
"""
from __future__ import annotations

from aughor.ontology.models import OntologyMetric
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
