"""Plane-conformance tests for the Semantic plane (AL-05) — `aughor/semantic/context.py`.

`resolve()` must COMPOSE the ad-hoc consultations (metrics, ontology, cached profile, KB) into one
`SemanticContext`, fail-open on any one source, and expose a JSON-safe `summary()`. Plus: the
`CapabilityRequest` carries it (the AL-02 ↔ AL-05 "Question × Scope × SemanticContext" tie), and the
`/query/semantic-context` consumer returns it. The consultations are monkeypatched so the test is
hermetic (no ontology cache / Qdrant needed).
"""
from __future__ import annotations

from aughor.semantic.context import resolve, SemanticContext
from aughor.capability import CapabilityRequest


class _FakeMetric:
    def __init__(self, name): self.name = name


class _FakeOntology:
    entities = {"order": 1, "customer": 2, "product": 3}
    relationships = {"order_customer": 1, "order_product": 2}


def _patch_all(monkeypatch, *, metrics=None, ontology=None, profile=None, kb=False):
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics",
                        lambda *a, **k: metrics if metrics is not None else [])
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda *a, **k: ontology)
    monkeypatch.setattr("aughor.profile.store.load_raw", lambda *a, **k: profile)
    monkeypatch.setattr("aughor.semantic.kb_retriever.has_strong_kb_match", lambda *a, **k: kb)


# ── Composition: resolve() bundles the four sources ──────────────────────────────────────

def test_resolve_composes_all_sources(monkeypatch):
    _patch_all(monkeypatch, metrics=[_FakeMetric("gmv"), _FakeMetric("aov")],
               ontology=_FakeOntology(), profile={"industry": "DTC Beauty"}, kb=True)
    ctx = resolve("why is gmv down", "fixture", "ecommerce")
    assert isinstance(ctx, SemanticContext)
    assert [m.name for m in ctx.metrics] == ["gmv", "aov"]
    assert ctx.ontology is not None
    assert ctx.profile == {"industry": "DTC Beauty"}
    assert ctx.has_kb_match is True
    assert ctx.scope_schema == "ecommerce"


def test_summary_shape(monkeypatch):
    _patch_all(monkeypatch, metrics=[_FakeMetric("gmv")], ontology=_FakeOntology(),
               profile={"industry": "DTC Beauty"}, kb=True)
    s = resolve("q", "fixture").summary()
    assert s["metric_count"] == 1
    assert s["metric_names"] == ["gmv"]
    assert s["has_ontology"] is True
    assert s["ontology_entities"] == 3
    assert s["ontology_relationships"] == 2
    assert s["profile_industry"] == "DTC Beauty"
    assert s["has_kb_match"] is True
    assert s["connection_id"] == "fixture"


# ── contracts(): the two metric shapes unified as SemanticContracts (REC-U10) ─────────────

class _OntoWithMetrics:
    def __init__(self, metrics): self.metrics = metrics


def test_contracts_unifies_catalog_and_ontology():
    from aughor.semantic.metrics import MetricDefinition
    from aughor.ontology.models import OntologyMetric
    ctx = SemanticContext(
        question="q", connection_id="c",
        metrics=[MetricDefinition(name="mrr", label="MRR", sql="SUM(a)")],
        ontology=_OntoWithMetrics({"rev": OntologyMetric(id="rev", display_name="Rev",
                                                          entity="order", formula_sql="SUM(t)")}),
    )
    by_key = {c.key: c for c in ctx.contracts()}
    assert set(by_key) == {"mrr", "rev"}
    assert by_key["mrr"].source == "catalog" and by_key["rev"].source == "ontology"


def test_contracts_catalog_wins_on_key_collision():
    from aughor.semantic.metrics import MetricDefinition
    from aughor.ontology.models import OntologyMetric
    ctx = SemanticContext(
        question="q", connection_id="c",
        metrics=[MetricDefinition(name="revenue", label="Revenue", sql="SUM(catalog)")],
        ontology=_OntoWithMetrics({"revenue": OntologyMetric(id="revenue", display_name="Revenue",
                                                             entity="order", formula_sql="SUM(onto)")}),
    )
    contracts = ctx.contracts()
    assert len(contracts) == 1                       # one key, not two
    assert contracts[0].source == "catalog"          # the human-governed definition wins
    assert contracts[0].sql == "SUM(catalog)"


def test_contracts_is_fail_open_on_bad_entry():
    from aughor.semantic.metrics import MetricDefinition
    # A junk ontology metric (missing required fields) is skipped, the good catalog one survives.
    ctx = SemanticContext(
        question="q", connection_id="c",
        metrics=[MetricDefinition(name="ok", label="OK", sql="SUM(a)")],
        ontology=_OntoWithMetrics({"bad": object()}),   # not an OntologyMetric → adapter raises
    )
    keys = [c.key for c in ctx.contracts()]           # must NOT raise
    assert keys == ["ok"]


def test_summary_reports_unified_contract_count():
    from aughor.semantic.metrics import MetricDefinition
    from aughor.ontology.models import OntologyMetric
    ctx = SemanticContext(
        question="q", connection_id="c",
        metrics=[MetricDefinition(name="mrr", label="MRR", sql="SUM(a)")],
        ontology=_OntoWithMetrics({"rev": OntologyMetric(id="rev", display_name="Rev",
                                                          entity="order", formula_sql="SUM(t)")}),
    )
    s = ctx.summary()
    assert s["metric_count"] == 1                     # catalog only
    assert s["contract_count"] == 2                   # catalog ∪ ontology


# ── contracts(): the THIRD store (profile north-star) + rank precedence (REC-U10) ─────────

def _profile_with_ns(name="gross_margin", value_sql="SUM(m)/NULLIF(SUM(p),0)"):
    return {"industry": "DTC", "north_star_metrics": [{
        "name": name, "definition": "gross margin rate", "maps_to": "t.m,t.p",
        "why_it_matters": "profit", "unit_or_range": "%", "value_sql": value_sql}]}


def test_contracts_includes_profile_north_star():
    from aughor.semantic.metrics import MetricDefinition
    ctx = SemanticContext(question="q", connection_id="c",
                          metrics=[MetricDefinition(name="mrr", label="MRR", sql="SUM(a)")],
                          profile=_profile_with_ns())
    by_key = {c.key: c for c in ctx.contracts()}
    assert set(by_key) == {"mrr", "gross_margin"}
    assert by_key["gross_margin"].source == "profile" and by_key["gross_margin"].is_trusted


def test_contracts_precedence_catalog_over_profile_over_ontology():
    from aughor.semantic.metrics import MetricDefinition
    from aughor.ontology.models import OntologyMetric
    ctx = SemanticContext(
        question="q", connection_id="c",
        metrics=[MetricDefinition(name="revenue", label="R", sql="SUM(catalog)")],
        ontology=_OntoWithMetrics({"revenue": OntologyMetric(id="revenue", display_name="R",
                                    entity="order", formula_sql="SUM(onto)", verified=True)}),
        profile=_profile_with_ns(name="revenue", value_sql="SUM(profile)"),
    )
    contracts = ctx.contracts()
    assert len(contracts) == 1                          # one key across all three stores
    assert contracts[0].source == "catalog" and contracts[0].sql == "SUM(catalog)"


def test_contracts_malformed_north_star_is_skipped():
    from aughor.semantic.metrics import MetricDefinition
    ctx = SemanticContext(question="q", connection_id="c",
                          metrics=[MetricDefinition(name="ok", label="OK", sql="SUM(a)")],
                          profile={"north_star_metrics": [{"name": "junk"}]})  # missing required fields
    keys = [c.key for c in ctx.contracts()]             # must NOT raise
    assert keys == ["ok"]


def test_summary_surfaces_serialized_contracts():
    from aughor.semantic.metrics import MetricDefinition
    ctx = SemanticContext(question="q", connection_id="c",
                          metrics=[MetricDefinition(name="mrr", label="MRR", sql="SUM(a)", unit="$")])
    s = ctx.summary()
    assert isinstance(s["contracts"], list)
    assert s["contract_count"] == len(s["contracts"]) == 1
    c0 = s["contracts"][0]
    assert c0["key"] == "mrr" and c0["source"] == "catalog" and c0["sql"] == "SUM(a)"


# ── Fail-open: one erroring source never sinks the resolve ────────────────────────────────

def test_resolve_is_fail_open(monkeypatch):
    _patch_all(monkeypatch, metrics=[_FakeMetric("gmv")], profile={"industry": "X"}, kb=True)

    def _boom(*a, **k):
        raise RuntimeError("ontology cache unreadable")
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", _boom)

    ctx = resolve("q", "fixture")            # must NOT raise
    assert ctx.ontology is None              # the erroring source degrades to its default
    assert [m.name for m in ctx.metrics] == ["gmv"]   # the others still resolved
    assert ctx.profile == {"industry": "X"}
    assert ctx.has_kb_match is True


def test_resolve_with_no_sources_is_empty_not_error(monkeypatch):
    _patch_all(monkeypatch)                  # everything empty/None/False
    ctx = resolve("q", "fixture")
    assert ctx.metrics == []
    assert ctx.ontology is None
    assert ctx.profile is None
    assert ctx.has_kb_match is False
    assert ctx.summary()["metric_count"] == 0


# ── AL-02 ↔ AL-05 tie: the Capability request carries the resolved context ────────────────

def test_capability_request_carries_semantic(monkeypatch):
    _patch_all(monkeypatch, metrics=[_FakeMetric("gmv")])
    ctx = resolve("q", "fixture")
    req = CapabilityRequest(question="q", semantic=ctx)
    assert req.semantic is ctx
    assert req.semantic.metrics[0].name == "gmv"


# ── The consumer: /query/semantic-context returns the resolved summary ────────────────────

def test_semantic_context_endpoint(client, builtin_conn_id):
    r = client.post("/query/semantic-context",
                    json={"conn_id": builtin_conn_id, "question": "top products by revenue"})
    assert r.status_code == 200
    body = r.json()
    # Shape is stable regardless of what the fixture happens to have cached.
    for key in ("question", "connection_id", "metric_count", "has_ontology", "has_kb_match"):
        assert key in body
    assert body["connection_id"] == builtin_conn_id
    # The unified metric contract is surfaced on the real HTTP path (REC-U10 display repoint).
    assert "contract_count" in body and isinstance(body["contracts"], list)
    assert len(body["contracts"]) == min(body["contract_count"], 100)
    for c in body["contracts"]:                          # each is a serialized SemanticContract
        assert {"key", "sql", "source"} <= set(c) and c["source"] in ("catalog", "profile", "ontology")


def test_semantic_context_endpoint_requires_conn(client):
    r = client.post("/query/semantic-context", json={"conn_id": "", "question": "q"})
    assert r.status_code == 400
