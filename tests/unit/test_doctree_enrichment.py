"""R8b — the optional LLM polish over the deterministic doc tree.

Enrichment is a DECORATION keyed to content_hash: the deterministic summary
stays authoritative for hashing, `best_summary()` never serves a stale polish,
the Merkle rebuild invalidates exactly the touched nodes, and the estimate gate
prices the pass before any spend. Width-routing sends wide tables to "coder".

Hermetic: a fake provider factory; no model, no network.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.ontology.doctree import (
    build_doc_tree,
    enrich_tree,
    estimate_enrichment,
)
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph


def _graph(desc: str = ""):
    ent = OntologyEntity(
        id="sales", display_name="Sales", source_tables=["sales"],
        identity_key="id", grain_verified=True, description=desc,
        properties={
            "brand": EntityProperty(name="brand", data_type="VARCHAR",
                                    semantic_type="dimension"),
            "amount": EntityProperty(name="amount", data_type="DOUBLE",
                                     semantic_type="measure"),
        },
    )
    return OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="f",
                         entities={"sales": ent})


class _Provider:
    """Records tiers requested; returns canned polished prose."""

    def __init__(self):
        self.tiers: list[str] = []

    def __call__(self, tier: str):
        self.tiers.append(tier)
        return SimpleNamespace(complete=lambda **kw: SimpleNamespace(
            summary="Polished: one row per sale, best for revenue questions."))


def test_enrich_sets_polish_and_best_summary_prefers_it():
    tree = build_doc_tree(_graph())
    provider = _Provider()
    out = enrich_tree(tree, provider_factory=provider)
    assert out == {"enriched": 1, "failed": 0, "routed": {"fast": 1, "coder": 0}}
    node = tree.nodes["s.sales"]
    assert node.enriched_summary.startswith("Polished:")
    assert node.enriched_hash == node.content_hash
    assert node.best_summary() == node.enriched_summary
    assert node.summary != node.enriched_summary        # the deterministic prose survives


def test_only_stale_skips_fresh_nodes():
    tree = build_doc_tree(_graph())
    provider = _Provider()
    enrich_tree(tree, provider_factory=provider)
    out2 = enrich_tree(tree, provider_factory=provider)  # everything fresh now
    assert out2["enriched"] == 0
    assert len(provider.tiers) == 1                      # exactly one LLM call ever


def test_merkle_rebuild_keeps_polish_on_unchanged_and_stales_changed():
    tree = build_doc_tree(_graph())
    enrich_tree(tree, provider_factory=_Provider())

    # Unchanged rebuild → _emit reuses the prior node, polish survives.
    same = build_doc_tree(_graph(), prior=tree)
    assert same.nodes["s.sales"].enriched_summary.startswith("Polished:")
    assert same.nodes["s.sales"].best_summary().startswith("Polished:")

    # A content change → fresh node, no polish carried; best_summary falls back.
    changed = build_doc_tree(_graph(), prior=tree,
                             table_stats={"sales": {"row_count": 999}})
    node = changed.nodes["s.sales"]
    assert node.best_summary() == node.summary
    assert estimate_enrichment(changed)["nodes"] == 1    # stale again → priced again


def test_estimate_prices_before_any_spend():
    tree = build_doc_tree(_graph())
    est = estimate_enrichment(tree)
    assert est["nodes"] == 1
    assert est["est_tokens"] > 0
    enrich_tree(tree, provider_factory=_Provider())
    assert estimate_enrichment(tree)["nodes"] == 0       # fully fresh → nothing to pay


def test_width_routing_sends_wide_tables_to_coder(monkeypatch):
    import aughor.ontology.doctree as dt
    monkeypatch.setattr(dt, "_ENRICH_WIDTH_TOKENS", 1)   # everything counts as wide
    tree = build_doc_tree(_graph())
    provider = _Provider()
    out = enrich_tree(tree, provider_factory=provider)
    assert out["routed"] == {"fast": 0, "coder": 1}
    assert provider.tiers == ["coder"]


def test_per_node_failure_keeps_deterministic_summary():
    tree = build_doc_tree(_graph())

    def _broken(tier):
        return SimpleNamespace(complete=lambda **kw: (_ for _ in ()).throw(
            RuntimeError("provider down")))

    out = enrich_tree(tree, provider_factory=_broken)
    assert out["enriched"] == 0 and out["failed"] == 1
    node = tree.nodes["s.sales"]
    assert node.enriched_summary == ""
    assert node.best_summary() == node.summary           # honest fallback
    assert estimate_enrichment(tree)["nodes"] == 1       # still stale → retried next pass


def test_index_doc_tree_embeds_the_polish(monkeypatch, tmp_path):
    import aughor.knowledge.indexer as idx
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(tmp_path / "documents.json"))
    upserts: list = []
    monkeypatch.setattr("aughor.semantic.embedder.embed",
                        lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr("aughor.semantic.vector_store.upsert",
                        lambda coll, points: upserts.extend(points))
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection", lambda coll: None)
    monkeypatch.setattr(idx, "_delete_doc_chunks", lambda doc_id: None)

    tree = build_doc_tree(_graph())
    enrich_tree(tree, provider_factory=_Provider())
    idx.index_doc_tree(tree, connection_id="c", schema="s")
    assert upserts and upserts[0]["payload"]["text"].startswith("Polished:")
