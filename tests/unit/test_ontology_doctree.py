"""R8 — the ontology doc-tree artifact.

Hermetic: builds a synthetic OntologyGraph (no DB, no model, no live stores) and exercises the
deterministic rollup, the per-table analyst questions, the Merkle incremental rebuild (cache-hit
accounting + subtree short-circuit), ignore-globs, the estimate-then-confirm dry-run, and the
file-per-node persistence roundtrip.
"""
from __future__ import annotations

import aughor.ontology.doctree as dt
from aughor.ontology.doctree import (build_doc_tree, estimate_doc_build, load_doc_tree,
                                     save_doc_tree)
from aughor.ontology.models import (EntityProperty, OntologyEntity, OntologyGraph,
                                    OntologyRelationship)


def _prop(name, semantic_type, **kw):
    return EntityProperty(name=name, display_name=kw.pop("display_name", name.replace("_", " ").title()),
                          semantic_type=semantic_type, **kw)


def _graph(*, include_tmp=True) -> OntologyGraph:
    order = OntologyEntity(
        id="Order", display_name="Order", description="A customer purchase",
        source_tables=["orders"], identity_key="order_id", grain_verified=True,
        entity_type="business_object", has_lifecycle=True, lifecycle_column="order_status",
        active_filter="order_status NOT IN ('canceled')",
        properties={
            "order_id": _prop("order_id", "identifier", data_type="INTEGER", is_primary_key=True),
            "customer_id": _prop("customer_id", "identifier", data_type="INTEGER", is_foreign_key=True),
            "amount": _prop("amount", "measure", data_type="DECIMAL", unit="USD",
                            value_interpretation="currency", measure_grain="per_line"),
            "order_status": _prop("order_status", "dimension", data_type="VARCHAR",
                                  sample_values=["placed", "shipped", "canceled"]),
            "created_at": _prop("created_at", "timestamp", data_type="TIMESTAMP"),
        },
    )
    customer = OntologyEntity(
        id="Customer", display_name="Customer", source_tables=["customers"],
        identity_key="customer_id", grain_verified=True, entity_type="reference_data",
        properties={
            "customer_id": _prop("customer_id", "identifier", data_type="INTEGER", is_primary_key=True),
            "region": _prop("region", "dimension", data_type="VARCHAR",
                            sample_values=["US", "EU", "APAC"]),
            "signup_date": _prop("signup_date", "timestamp", data_type="DATE"),
        },
    )
    entities = {"Order": order, "Customer": customer}
    if include_tmp:
        entities["TmpScratch"] = OntologyEntity(
            id="TmpScratch", display_name="Tmp Scratch", source_tables=["tmp_scratch"],
            identity_key="id", grain_verified=False, entity_type="standalone",
            properties={"id": _prop("id", "identifier", data_type="INTEGER")},
        )
    rel = OntologyRelationship(
        id="Order_RELATES_TO_Customer", from_entity="Order", to_entity="Customer",
        cardinality="N:1", join_sql="orders.customer_id = customers.customer_id",
        from_table="orders", from_col="customer_id", to_table="customers", to_col="customer_id",
    )
    return OntologyGraph(
        connection_id="test_conn", schema_name="analytics", schema_fingerprint="fp_v1",
        entities=entities, relationships={rel.id: rel},
    )


# ── deterministic rollup ──────────────────────────────────────────────────────

def test_builds_the_full_hierarchy():
    tree = build_doc_tree(_graph())
    kinds = {n.kind for n in tree.nodes.values()}
    assert kinds == {"column", "table", "schema", "connection"}
    # connection → schema → tables → columns fqns
    assert "test_conn" in tree.nodes and tree.nodes["test_conn"].kind == "connection"
    assert "analytics" in tree.nodes and tree.nodes["analytics"].kind == "schema"
    assert "analytics.Order" in tree.nodes
    assert "analytics.Order.amount" in tree.nodes
    assert tree.root_checksum == tree.nodes["test_conn"].checksum


def test_table_summary_rolls_up_columns_and_relationships():
    tree = build_doc_tree(_graph())
    order = tree.nodes["analytics.Order"]
    assert order.facts["n_measures"] == 1 and order.facts["n_dimensions"] == 1
    assert order.facts["grain_verified"] is True
    assert "Customer (N:1)" in order.facts["relationships"]
    assert "grain: order_id (verified)" in order.summary
    # a table folds its columns' checksums as children
    assert "analytics.Order.amount" in order.children
    assert order.child_checksums["analytics.Order.amount"] == tree.nodes["analytics.Order.amount"].checksum


def test_analyst_questions_are_seeded_from_real_columns():
    tree = build_doc_tree(_graph())
    qs = tree.nodes["analytics.Order"].questions
    assert len(qs) == 3
    joined = " ".join(qs).lower()
    assert "amount" in joined            # the measure
    assert "order status" in joined      # the dimension
    # never fabricates a measure a table lacks:
    cust_qs = " ".join(tree.nodes["analytics.Customer"].questions).lower()
    assert "amount" not in cust_qs


# ── ignore-globs ──────────────────────────────────────────────────────────────

def test_ignore_globs_skip_scaffolding_tables():
    tree = build_doc_tree(_graph(include_tmp=True))
    assert "analytics.TmpScratch" not in tree.nodes
    assert "tmp_scratch" in tree.stats["skipped_tables"]
    assert tree.stats["tables"] == 2   # Order + Customer, not TmpScratch


def test_custom_ignore_list_overrides_default():
    # empty ignore list → nothing skipped, tmp table documented
    tree = build_doc_tree(_graph(include_tmp=True), ignore=())
    assert "analytics.TmpScratch" in tree.nodes
    assert tree.stats["skipped_tables"] == []


# ── Merkle incremental rebuild ────────────────────────────────────────────────

def test_unchanged_rebuild_is_all_cache_hits():
    g = _graph()
    tree1 = build_doc_tree(g)
    tree2 = build_doc_tree(g, prior=tree1)
    assert tree2.stats["rebuilt"] == 0
    assert tree2.stats["cache_hits"] == len(tree2.nodes)
    # every node object is reused verbatim
    for fqn, node in tree2.nodes.items():
        assert node is tree1.nodes[fqn]


def test_changing_one_column_rebuilds_only_its_path_to_root():
    g = _graph()
    tree1 = build_doc_tree(g)
    # change one column's type — only amount, its table, the schema, and the connection should move
    g.entities["Order"].properties["amount"].data_type = "DOUBLE"
    tree2 = build_doc_tree(g, prior=tree1)

    assert tree2.nodes["analytics.Order.amount"] is not tree1.nodes["analytics.Order.amount"]
    assert tree2.nodes["analytics.Order"] is not tree1.nodes["analytics.Order"]        # child moved
    assert tree2.nodes["analytics"] is not tree1.nodes["analytics"]                    # up the tree
    assert tree2.nodes["test_conn"] is not tree1.nodes["test_conn"]
    # untouched subtree is reused verbatim
    assert tree2.nodes["analytics.Customer"] is tree1.nodes["analytics.Customer"]
    assert tree2.nodes["analytics.Order.order_id"] is tree1.nodes["analytics.Order.order_id"]
    # the root checksum genuinely changed
    assert tree2.root_checksum != tree1.root_checksum


# ── estimate-then-confirm ─────────────────────────────────────────────────────

def test_estimate_reports_counts_and_zero_spend():
    est = estimate_doc_build(_graph())
    assert est["tables"] == 2 and est["nodes"] == len(build_doc_tree(_graph()).nodes)
    assert est["llm_tokens"] == 0 and est["deterministic"] is True
    assert est["would_rebuild"] > 0 and est["would_reuse"] == 0   # no prior → all fresh


def test_estimate_against_prior_shows_reuse():
    g = _graph()
    prior = build_doc_tree(g)
    est = estimate_doc_build(g, prior=prior)
    assert est["would_rebuild"] == 0 and est["would_reuse"] == est["nodes"]


# ── table_stats enrichment ────────────────────────────────────────────────────

def test_table_stats_enrich_table_facts_and_summary():
    tree = build_doc_tree(_graph(), table_stats={
        "Order": {"row_count": 12000, "date_range": "2020 → 2025", "time_grain": "month"},
    })
    order = tree.nodes["analytics.Order"]
    assert order.facts["row_count"] == 12000 and order.facts["date_range"] == "2020 → 2025"
    assert "12,000 rows" in order.summary


# ── persistence roundtrip ─────────────────────────────────────────────────────

def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "_ROOT", tmp_path)
    tree = build_doc_tree(_graph())
    save_doc_tree(tree)
    loaded = load_doc_tree("test_conn", "analytics")
    assert loaded is not None
    assert loaded.root_checksum == tree.root_checksum
    assert set(loaded.nodes) == set(tree.nodes)
    assert loaded.nodes["analytics.Order"].questions == tree.nodes["analytics.Order"].questions
    # a reload used as prior is a full cache hit (checksums survived the roundtrip)
    tree2 = build_doc_tree(_graph(), prior=loaded)
    assert tree2.stats["rebuilt"] == 0


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "_ROOT", tmp_path)
    assert load_doc_tree("nope", "nope") is None


def test_empty_schema_does_not_collide_with_connection():
    g = _graph()
    g.schema_name = ""
    tree = build_doc_tree(g)
    assert "default" in tree.nodes and tree.nodes["default"].kind == "schema"
    assert tree.nodes["test_conn"].kind == "connection"
    assert tree.nodes["default"].checksum != tree.nodes["test_conn"].checksum
