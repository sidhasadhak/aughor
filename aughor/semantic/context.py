"""The Semantic plane's resolve-once entry (AL-05) — `resolve(question, scope) -> SemanticContext`.

The review's "single biggest architectural gap": the platform's crown-jewel semantic material
(governed metrics, the ontology, the business profile, the knowledge base) is consulted **ad-hoc**,
scattered across ~9 inline calls in the answer pipeline (`agent/nodes.py`, `routers/investigations.py`)
— it is not a plane in the request path. This resolves it **once**, composing the existing
consultations (delegation, not rewrite) into one `SemanticContext` that orchestration can attach to a
request and every downstream step can read without re-resolving.

Fail-open by construction: each consultation is independently guarded, so a missing ontology, an empty
metrics catalogue, or an unreachable KB just leaves that field at its default — `resolve` never raises.
The heavier "thread this through every node of the live streaming path" wiring is the deferred broad
migration; this slice builds the plane + a read-only consumer (`/query/semantic-context`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SemanticContext:
    """Resolved semantic material for a question — the Semantic plane's return type.

    `metrics` are the governed KPI formulas (optionally schema-filtered); `ontology` is the cached
    object model; `profile` the cached business profile; `has_kb_match` whether the KB strongly
    covers the question (the signal that routes definitional asks to a text answer)."""
    question: str
    connection_id: str
    scope_schema: str | None = None
    metrics: list = field(default_factory=list)          # list[MetricDefinition]
    ontology: Any = None                                 # OntologyGraph | None
    profile: dict | None = None                          # cached business profile (raw dict)
    has_kb_match: bool = False

    def summary(self) -> dict:
        """A JSON-safe digest — what the platform knows about this question. For the API surface."""
        ents = getattr(self.ontology, "entities", {}) or {}
        rels = getattr(self.ontology, "relationships", {}) or {}
        return {
            "question": self.question,
            "connection_id": self.connection_id,
            "scope_schema": self.scope_schema,
            "metric_count": len(self.metrics),
            "metric_names": [getattr(m, "name", str(m)) for m in self.metrics][:20],
            "has_ontology": self.ontology is not None,
            "ontology_entities": len(ents),
            "ontology_relationships": len(rels),
            "has_profile": self.profile is not None,
            "profile_industry": (self.profile or {}).get("industry") if isinstance(self.profile, dict) else None,
            "has_kb_match": self.has_kb_match,
        }


def _tolerate(exc: Exception, where: str) -> None:
    try:
        from aughor.kernel.errors import tolerate
        tolerate(exc, where, counter="semantic.resolve")
    except Exception:
        pass


def resolve(question: str, connection_id: str, scope_schema: str | None = None, *,
            schema_text: str = "") -> SemanticContext:
    """Resolve the Semantic plane for one question — compose the ad-hoc consultations into one
    context. Never raises; each piece is fail-open (a missing/erroring source leaves its default).

    `schema_text`, when supplied, filters global metrics to those whose tables/columns exist in the
    scoped schema (metrics are global, so this stops one connection's metric leaking into another)."""
    ctx = SemanticContext(question=question or "", connection_id=connection_id or "",
                          scope_schema=scope_schema)

    # Governed metric formulas, optionally filtered to the scoped schema.
    try:
        from aughor.semantic.metrics import list_metrics, filter_metrics_to_schema
        metrics = list_metrics()
        ctx.metrics = filter_metrics_to_schema(metrics, schema_text) if schema_text else metrics
    except Exception as exc:
        _tolerate(exc, "semantic.resolve: metrics")

    # The cached ontology (object model) for this connection + schema.
    try:
        from aughor.ontology.store import load_latest_ontology
        ctx.ontology = load_latest_ontology(connection_id, scope_schema)
    except Exception as exc:
        _tolerate(exc, "semantic.resolve: ontology")

    # The cached business profile — read-only load, never triggers LLM inference here.
    try:
        from aughor.profile.store import load_raw
        ctx.profile = load_raw(connection_id, scope_schema)
    except Exception as exc:
        _tolerate(exc, "semantic.resolve: profile")

    # Whether the knowledge base strongly covers the question (fail-open — KB may be unreachable).
    try:
        from aughor.semantic.kb_retriever import has_strong_kb_match
        ctx.has_kb_match = bool(has_strong_kb_match(question))
    except Exception as exc:
        _tolerate(exc, "semantic.resolve: kb")

    return ctx


def resolve_if_enabled(question: str, connection_id: str, scope_schema: str | None = None, *,
                       schema_text: str = "") -> SemanticContext | None:
    """Resolve the Semantic plane only when the `semantic.resolve_live` flag is on; else `None`
    (the plane stays dormant, the answer path unchanged). This keeps the flag check + the fail-open
    at the plane boundary, so the router/seed site is a single call — the AL-05 live wire."""
    try:
        from aughor.kernel.flags import flag_enabled
        if not flag_enabled("semantic.resolve_live"):
            return None
        return resolve(question, connection_id, scope_schema, schema_text=schema_text)
    except Exception as exc:
        _tolerate(exc, "semantic.resolve_if_enabled")
        return None
