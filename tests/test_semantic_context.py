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


def test_semantic_context_endpoint_requires_conn(client):
    r = client.post("/query/semantic-context", json={"conn_id": "", "question": "q"})
    assert r.status_code == 400
