"""The verified entity graph reaches the SQL prompt (ROADMAP §3 / Semantic-Views study).

The ontology's relationships carry cardinality, join_confidence and the probed
value_overlap — and none of it reached the prompt: builder.render_ontology_annotations
deliberately skips relationships ("already covered by JOIN HINTS") while JOIN HINTS is
name-heuristic only. `render_relationship_block` closes the gap: verified/exact edges
only, existence-bound to the schema being rendered, in a format the schema linker's
trailing-content pass does not strip.
"""
from __future__ import annotations

from aughor.ontology.models import OntologyGraph, OntologyRelationship
from aughor.ontology.semantic_block import render_relationship_block


def _rel(rid, ft, fc, tt, tc, *, conf="verified", card="N:1", overlap=None,
         nullable=False, verb="RELATES_TO", fe="From", te="To"):
    return OntologyRelationship(
        id=rid, from_entity=fe, to_entity=te, verb=verb, cardinality=card,
        join_sql=f"{ft}.{fc} = {tt}.{tc}", from_table=ft, from_col=fc,
        to_table=tt, to_col=tc, join_confidence=conf, value_overlap=overlap,
        nullable=nullable)


def _graph(*rels):
    return OntologyGraph(connection_id="c", schema_fingerprint="f",
                         relationships={r.id: r for r in rels})


_TABLE_COLS = {
    "orders": ["order_id", "customer_id", "amount"],
    "customers": ["customer_id", "name"],
}


def test_verified_edge_renders_cardinality_confidence_and_overlap():
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id",
                    overlap=0.97))
    block = render_relationship_block(g, _TABLE_COLS)
    assert "ENTITY RELATIONSHIPS" in block
    assert "- orders.customer_id → customers.customer_id [N:1, verified, 97% key overlap]" in block
    assert "CARDINALITY" in block     # the fan-out guidance ships with the edges


def test_exact_renders_and_inferred_does_not():
    g = _graph(
        _rel("R1", "orders", "customer_id", "customers", "customer_id", conf="exact"),
        _rel("R2", "orders", "amount", "customers", "name", conf="inferred"),
    )
    block = render_relationship_block(g, _TABLE_COLS)
    assert "[N:1, exact]" in block
    assert "amount" not in block      # a name-guess adds nothing over JOIN HINTS


def test_existence_binding_drops_stale_tables_and_columns():
    g = _graph(
        _rel("R1", "orders", "customer_id", "archived", "customer_id"),   # table gone
        _rel("R2", "orders", "legacy_cust_id", "customers", "customer_id"),  # column gone
    )
    assert render_relationship_block(g, _TABLE_COLS) == ""


def test_ambiguous_bare_name_never_binds_to_a_twin():
    # Two schemas expose a `customers`; a bare-named edge must bind to neither.
    cols = {"a.customers": ["customer_id"], "b.customers": ["customer_id"],
            "orders": ["order_id", "customer_id"]}
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id"))
    assert render_relationship_block(g, cols) == ""


def test_qualified_graph_edge_binds_to_the_schemas_own_spelling():
    g = _graph(_rel("R1", "analytics.orders", "customer_id",
                    "analytics.customers", "customer_id"))
    block = render_relationship_block(g, _TABLE_COLS)
    # rendered as the CURRENT schema spells the tables, not as the cache does
    assert "- orders.customer_id → customers.customer_id" in block


def test_empty_inputs_render_nothing():
    assert render_relationship_block(None, _TABLE_COLS) == ""
    assert render_relationship_block(_graph(), _TABLE_COLS) == ""
    assert render_relationship_block(
        _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id")), {}) == ""


def test_cap_sheds_exact_edges_before_verified_ones():
    from aughor.ontology import semantic_block as sb
    cols = {f"t{i}": ["k"] for i in range(60)}
    cols["hub"] = ["k"]
    rels = [_rel(f"E{i}", f"t{i}", "k", "hub", "k", conf="exact") for i in range(50)]
    rels.append(_rel("V1", "t59", "k", "hub", "k", conf="verified"))
    block = render_relationship_block(_graph(*rels), cols)
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) == sb._MAX_RELATIONSHIP_LINES
    assert any("verified" in ln for ln in lines)   # the verified edge survived the cut


def test_nullable_fk_gets_the_left_join_warning():
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id",
                    nullable=True))
    block = render_relationship_block(g, _TABLE_COLS)
    assert "nullable FK" in block and "LEFT JOIN" in block
    g2 = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id"))
    assert "LEFT JOIN" not in render_relationship_block(g2, _TABLE_COLS)


def test_enriched_verb_is_shown_and_the_placeholder_is_not():
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id",
                    verb="placed by", fe="Order", te="Customer"))
    block = render_relationship_block(g, _TABLE_COLS)
    assert "Order placed by Customer" in block
    g2 = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id"))
    assert "RELATES_TO" not in render_relationship_block(g2, _TABLE_COLS)


# ── The block survives the schema linker's trailing-content pass ──────────────
# link_schema strips 2-space-indented trailing lines (it guts the JOIN HINTS
# detail on a filtered slice) — the `- ` bullet format exists so the verified
# edges are NOT lost the same way. This pins that property.

def test_relationship_lines_survive_schema_linking():
    from aughor.tools.schema_linker import link_schema
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id",
                    overlap=0.97))
    block = render_relationship_block(g, _TABLE_COLS)
    schema = (
        "TABLE: orders (100 rows)\n  order_id  INTEGER\n  customer_id  INTEGER\n"
        "  amount  DOUBLE\n\n"
        "TABLE: customers (10 rows)\n  customer_id  INTEGER\n  name  VARCHAR\n\n"
        + block + "\n"
    )
    out = link_schema("total order amount by customer name", schema,
                      top_k_tables=1, top_k_cols=2)
    assert out != schema                      # the linker actually filtered
    assert "- orders.customer_id → customers.customer_id [N:1, verified, 97% key overlap]" in out


def test_parse_schema_tables_does_not_absorb_the_block():
    from aughor.tools.schema import parse_schema_tables
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id"))
    block = render_relationship_block(g, _TABLE_COLS)
    schema = "TABLE: orders (100 rows)\n  order_id  INTEGER\n\n" + block + "\n"
    parsed = parse_schema_tables(schema)
    assert parsed == {"orders": ["order_id"]}


# ── Wiring: apply_schema_enrichment appends the block from the cached graph ───

def test_apply_schema_enrichment_appends_the_block(monkeypatch):
    from aughor.ontology import store as onto_store
    from aughor.tools.schema import apply_schema_enrichment
    g = _graph(_rel("R1", "orders", "customer_id", "customers", "customer_id",
                    overlap=0.97))
    monkeypatch.setattr(onto_store, "load_latest_ontology", lambda cid, sn=None: g)
    raw = ("TABLE: orders (100 rows)\n  order_id  INTEGER\n  customer_id  INTEGER\n\n"
           "TABLE: customers (10 rows)\n  customer_id  INTEGER\n  name  VARCHAR\n")
    out = apply_schema_enrichment(raw, connection_id="connR")
    assert "ENTITY RELATIONSHIPS" in out
    assert "- orders.customer_id → customers.customer_id [N:1, verified, 97% key overlap]" in out


def test_apply_schema_enrichment_without_a_graph_is_unchanged(monkeypatch):
    from aughor.ontology import store as onto_store
    from aughor.tools.schema import apply_schema_enrichment
    raw = ("TABLE: orders (100 rows)\n  order_id  INTEGER\n  customer_id  INTEGER\n\n"
           "TABLE: customers (10 rows)\n  customer_id  INTEGER\n  name  VARCHAR\n")
    monkeypatch.setattr(onto_store, "load_latest_ontology", lambda cid, sn=None: None)
    assert "ENTITY RELATIONSHIPS" not in apply_schema_enrichment(raw, connection_id="connR")
    # no connection at all (fixture rendering) → the block never loads either
    assert "ENTITY RELATIONSHIPS" not in apply_schema_enrichment(raw)


# ── Wiring: the deep-analysis grounded schema carries the block ───────────────
# _build_grounded_schema filters with _filter_schema (TABLE-block-only — it drops
# the schema-wide ENTITY RELATIONSHIPS block enrichment appended) and re-attaches
# only the name-heuristic infer_joins hints, so the deep coder never saw the
# verified edges. The block is re-appended AFTER the filter, existence-bound to
# the KEPT tables so a dropped table's edge stays out of the prompt.

_DEEP_SCHEMA = (
    "TABLE: orders (100 rows)\n  order_id  INTEGER\n  customer_id  INTEGER\n"
    "  amount  DOUBLE\n  created_at  DATE\n\n"
    "TABLE: customers (10 rows)\n  customer_id  INTEGER\n  name  VARCHAR\n\n"
    "TABLE: vendors (5 rows)\n  vendor_key  INTEGER\n  vendor_label  VARCHAR\n\n"
    "TABLE: payments (50 rows)\n  payment_key  INTEGER\n  vendor_key  INTEGER\n"
)


def test_grounded_schema_appends_verified_edges_for_kept_tables_only(monkeypatch):
    from aughor.agent.investigate import _build_grounded_schema
    from aughor.ontology import store as onto_store
    g = _graph(
        _rel("R1", "orders", "customer_id", "customers", "customer_id", overlap=0.97),
        _rel("R2", "payments", "vendor_key", "vendors", "vendor_key"),
    )
    monkeypatch.setattr(onto_store, "load_latest_ontology", lambda cid, sn=None: g)
    out = _build_grounded_schema(
        _DEEP_SCHEMA, "orders", ["customers.name"], "orders.created_at",
        "total order amount by customer", connection_id="connD")
    assert "ENTITY RELATIONSHIPS" in out
    assert "- orders.customer_id → customers.customer_id [N:1, verified, 97% key overlap]" in out
    # premise: the filter really dropped the payments/vendors tables …
    assert "TABLE: payments" not in out and "TABLE: vendors" not in out
    # … so their edge — verified, and both tables live in the FULL schema — must
    # not render: existence binds to the filtered slice, not the full schema.
    assert "- payments.vendor_key" not in out


def test_grounded_schema_without_connection_or_graph_is_unchanged(monkeypatch):
    from aughor.agent.investigate import _build_grounded_schema
    from aughor.ontology import store as onto_store
    calls: list = []
    monkeypatch.setattr(onto_store, "load_latest_ontology",
                        lambda cid, sn=None: calls.append(cid))
    base = _build_grounded_schema(_DEEP_SCHEMA, "orders", ["customers.name"],
                                  "orders.created_at", "q")
    assert "TABLE: orders" in base and "ENTITY RELATIONSHIPS" not in base
    assert calls == []            # no connection_id ⇒ the cache is never touched
    out = _build_grounded_schema(_DEEP_SCHEMA, "orders", ["customers.name"],
                                 "orders.created_at", "q", connection_id="connD")
    assert out == base            # a connection with no cached graph changes nothing
    assert calls == ["connD"]


def test_grounded_schema_tolerates_a_failing_ontology_load(monkeypatch):
    from aughor.agent.investigate import _build_grounded_schema
    from aughor.ontology import store as onto_store

    def _boom(cid, sn=None):
        raise RuntimeError("ontology cache unavailable")

    monkeypatch.setattr(onto_store, "load_latest_ontology", _boom)
    out = _build_grounded_schema(_DEEP_SCHEMA, "orders", ["customers.name"],
                                 "orders.created_at", "q", connection_id="connD")
    assert "TABLE: orders" in out and "ENTITY RELATIONSHIPS" not in out
