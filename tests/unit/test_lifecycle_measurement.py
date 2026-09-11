"""ON-0a, second commit: lifecycle terminal states are MEASURED against the data.

A snapshot proves two contradictions — an observed state the lists never named, and a
claimed terminal state whose timestamp is set on rows now in another state — and can only
report an end-state name missing from the terminal set as unconfirmed. These tests pin the
verdicts, the segment downgrade, the rendered check, and the ratchet on the committed
samples fixture whose terminal set omits `refunded`.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from aughor.db.connection import open_connection
from aughor.ontology.builder import render_ontology_annotations
from aughor.ontology.lifecycle import apply_lifecycle_measurements, measure_entity, observed_states, rows_that_left
from aughor.ontology.models import OntologyEntity, OntologyGraph, Segment
from aughor.ontology.semantic_block import render_semantic_layer

REPO = Path(__file__).resolve().parents[2]
SAMPLES_FIXTURE = REPO / "evals" / "ablation_samples_ecommerce_ontology.json"
LUX_FIXTURE = REPO / "evals" / "ablation_luxexperience_ontology.json"


def _db(tmp_path, ddl: str, schema: str | None = None):
    """`schema` scopes the search path the way a registered connection's schema does — the
    served samples graph names its table `orders`, unqualified, and resolves through it."""
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute(ddl)
    con.close()
    return open_connection("duckdb", str(path), connection_id="t", schema_name=schema)


def _order(states, terminal, table="ecommerce.orders", segments=True) -> OntologyEntity:
    e = OntologyEntity(id="Order", display_name="Order", source_tables=[table], identity_key="order_id",
                       grain_verified=True, has_lifecycle=True, lifecycle_column="status",
                       lifecycle_states=list(states), terminal_states=list(terminal))
    if segments:
        tl = ", ".join(f"'{s}'" for s in terminal)
        e.segments["active_orders"] = Segment(id="active_orders", display_name="Active Orders",
                                              filter_sql=f"status NOT IN ({tl})", is_default=True,
                                              source="lifecycle", verified=True)
        e.segments["delivered_orders"] = Segment(id="delivered_orders", display_name="Delivered Orders",
                                                 filter_sql="status = 'delivered'", source="lifecycle", verified=True)
    return e


def _graph(*entities) -> OntologyGraph:
    return OntologyGraph(connection_id="c", schema_name="ecommerce", schema_fingerprint="f",
                         entities={e.id: e for e in entities})


_ORDERS = """
CREATE SCHEMA ecommerce;
CREATE TABLE ecommerce.orders (order_id INT, status VARCHAR, delivered_at DATE);
INSERT INTO ecommerce.orders VALUES
  (1,'delivered','2026-01-01'), (2,'delivered','2026-01-02'), (3,'delivered','2026-01-03'),
  (4,'shipped',NULL), (5,'shipped',NULL), (6,'cancelled',NULL),
  (7,'refunded',NULL), (8,'refunded',NULL), (9,'pending',NULL), (10,'on_hold',NULL),
  (11,'returned','2026-01-04');
"""


def test_observed_domain_and_rows_that_left(tmp_path):
    db = _db(tmp_path, _ORDERS)
    try:
        obs = observed_states(db, "ecommerce.orders", "status")
        assert obs == {"delivered": 3, "shipped": 2, "cancelled": 1, "refunded": 2, "pending": 1, "on_hold": 1, "returned": 1}
        assert observed_states(db, "ecommerce.orders", "no_such_col") is None
        # one row is 'returned' with delivered_at set: it passed through delivered and moved on
        assert rows_that_left(db, "ecommerce.orders", "status", "delivered") == 1
        assert rows_that_left(db, "ecommerce.orders", "status", "cancelled") is None   # no cancelled_at column
        assert rows_that_left(db, "ecommerce.orders", "status", "not an ident") is None
    finally:
        db.close()


def test_a_clean_lifecycle_measures_true_with_an_empty_note(tmp_path):
    db = _db(tmp_path, "CREATE SCHEMA ecommerce; CREATE TABLE ecommerce.orders (order_id INT, status VARCHAR);"
                       "INSERT INTO ecommerce.orders VALUES (1,'pending'), (2,'shipped'), (3,'delivered'), (4,'cancelled');")
    try:
        e = _order(["pending", "shipped", "delivered", "cancelled"], ["delivered", "cancelled"])
        m = measure_entity(db, e)
        assert m.verdict is True and m.note == "" and not m.unconfirmed and not m.vanished
    finally:
        db.close()


def test_an_unlisted_observed_state_contradicts_and_downgrades_the_derived_segment(tmp_path):
    db = _db(tmp_path, _ORDERS)
    try:
        e = _order(["pending", "shipped", "delivered", "cancelled", "refunded", "returned"], ["delivered", "cancelled", "refunded", "returned"])
        g = _graph(e)
        report = apply_lifecycle_measurements(g, db)
        assert e.lifecycle_verified is False
        assert "contradicted: observed but unlisted 'on_hold' (1 rows)" in e.lifecycle_note
        assert e.segments["active_orders"].verified is False
        assert e.segments["active_orders"].verification_note.startswith("derived from a contradicted lifecycle")
        assert e.segments["delivered_orders"].verified is True          # not derived from the terminal set
        assert [m.entity_id for m in report.contradicted] == ["Order"]
    finally:
        db.close()


def test_a_terminal_state_rows_left_is_refuted_by_its_timestamp(tmp_path):
    db = _db(tmp_path, _ORDERS)
    try:
        e = _order(["pending", "shipped", "delivered", "cancelled", "refunded", "returned", "on_hold"], ["delivered"])
        m = measure_entity(db, e)
        assert m.verdict is False and m.refuted == {"delivered": 1}
        assert "'delivered' is not terminal — 1 rows left it" in m.note
    finally:
        db.close()


def test_an_end_state_name_missing_from_the_terminal_set_is_unconfirmed_not_contradicted(tmp_path):
    db = _db(tmp_path, "CREATE SCHEMA ecommerce; CREATE TABLE ecommerce.orders (order_id INT, status VARCHAR);"
                       "INSERT INTO ecommerce.orders VALUES (1,'pending'), (2,'delivered'), (3,'cancelled'), (4,'refunded'), (5,'refunded');")
    try:
        e = _order(["pending", "delivered", "cancelled", "refunded"], ["delivered", "cancelled"])
        g = _graph(e)
        apply_lifecycle_measurements(g, db)
        assert e.lifecycle_verified is True
        assert e.lifecycle_note.startswith("unconfirmed: 'refunded' (2 rows) reads as an end state")
        assert e.segments["active_orders"].verified is True             # a suspicion changes no verdict
        block = render_ontology_annotations(g)
        assert "terminal states: 'delivered', 'cancelled'" in block
        assert "lifecycle check: unconfirmed: 'refunded' (2 rows)" in block
    finally:
        db.close()


def test_an_unreadable_column_is_unmeasurable_and_untouched(tmp_path):
    db = _db(tmp_path, "CREATE SCHEMA ecommerce; CREATE TABLE ecommerce.orders (order_id INT);")
    try:
        e = _order(["pending"], ["delivered"])
        report = apply_lifecycle_measurements(_graph(e), db)
        assert e.lifecycle_verified is None and e.lifecycle_note.startswith("not measurable")
        assert e.segments["active_orders"].verified is True
        assert report.summary()["unmeasurable"] == ["Order"]
        assert measure_entity(db, OntologyEntity(id="X", display_name="X", source_tables=["ecommerce.orders"],
                                                 identity_key="order_id", grain_verified=True)) is None
    finally:
        db.close()


def test_a_contradicted_lifecycle_leaves_the_semantic_layer_and_marks_the_entity_model(tmp_path):
    db = _db(tmp_path, _ORDERS)
    try:
        e = _order(["pending", "shipped", "delivered", "cancelled"], ["delivered", "cancelled"])
        g = _graph(e)
        before = render_semantic_layer(g, ["ecommerce.orders"])
        assert '"Active Orders" (ecommerce.orders)' in before
        apply_lifecycle_measurements(g, db)
        after = render_semantic_layer(g, ["ecommerce.orders"])
        assert "Active Orders" not in after and "Delivered Orders" in after
        assert "lifecycle check: contradicted:" in render_ontology_annotations(g)
    finally:
        db.close()


# ── The ratchet on the committed fixtures ─────────────────────────────────────────────────
_SAMPLES_SHAPE = """
CREATE SCHEMA ecommerce;
CREATE TABLE ecommerce.orders (order_id INT, status VARCHAR, order_date DATE, shipped_at DATE, delivered_at DATE);
INSERT INTO ecommerce.orders
  SELECT i, 'delivered', '2026-01-01', '2026-01-02', '2026-01-03' FROM range(25) t(i) UNION ALL
  SELECT 100+i, 'shipped', '2026-01-01', NULL, NULL FROM range(8) t(i) UNION ALL
  SELECT 200+i, 'cancelled', '2026-01-01', '2026-01-02', NULL FROM range(6) t(i) UNION ALL
  SELECT 300+i, 'refunded', '2026-01-01', '2026-01-02', NULL FROM range(5) t(i) UNION ALL
  SELECT 400+i, 'processing', '2026-01-01', NULL, NULL FROM range(3) t(i) UNION ALL
  SELECT 500+i, 'pending', '2026-01-01', NULL, NULL FROM range(2) t(i);
"""


def test_the_served_samples_graph_omits_refunded_and_the_measurement_says_so(tmp_path):
    g = OntologyGraph.model_validate(json.loads(SAMPLES_FIXTURE.read_text()))
    order = g.entities["Order"]
    assert order.terminal_states == ["delivered", "cancelled"] and "refunded" in order.lifecycle_states   # fails closed
    db = _db(tmp_path, _SAMPLES_SHAPE, schema="ecommerce")
    try:
        report = apply_lifecycle_measurements(g, db)
        assert order.lifecycle_verified is True                        # nothing the snapshot can refute
        assert order.lifecycle_note.startswith("unconfirmed: 'refunded' (5 rows) reads as an end state")
        assert [m.entity_id for m in report.unconfirmed] == ["Order"] and not report.contradicted
        assert "lifecycle check: unconfirmed: 'refunded'" in render_ontology_annotations(g)
    finally:
        db.close()


def test_the_served_luxexperience_lifecycles_measure_as_expected(tmp_path):
    g = OntologyGraph.model_validate(json.loads(LUX_FIXTURE.read_text()))
    ddl = """
    CREATE SCHEMA luxexperience;
    CREATE TABLE luxexperience.payments (payment_id INT, status VARCHAR);
    INSERT INTO luxexperience.payments VALUES (1,'captured'), (2,'captured'), (3,'refunded'), (4,'failed');
    CREATE TABLE luxexperience.return_logistics (return_logistics_id INT, condition VARCHAR);
    INSERT INTO luxexperience.return_logistics VALUES (1,'resellable'), (2,'minor_refurbish'), (3,'reject');
    """
    db = _db(tmp_path, ddl)
    try:
        report = apply_lifecycle_measurements(g, db)
        by = {m.entity_id: m for m in report.measurements}
        assert by["Payment"].verdict is True and by["Payment"].unconfirmed == {"refunded": 1}
        assert by["ReturnLogistic"].verdict is True and by["ReturnLogistic"].note == ""
    finally:
        db.close()
