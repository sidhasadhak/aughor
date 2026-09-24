"""PENDING item 27 — a measure that must not be summed across periods can be declared, and is held to it on every path.

A stock level is a reading AT a moment. Three daily readings of the same stock summed are three times the stock;
nothing could say so, and `SUM(on_hand)` over the snapshots compiled — and was written by the SQL writer — and answered
a number the data never held. A person now declares the property semiadditive (O5's word) over its reading's date, and:

* the object compiler refuses a sum that spans more than one date — as a measure, in a metric, through a link, through
  a formula that reads it, over a timeseries binding's readings or in a frame that sums them — while a sum within one
  date, an average per date, and an average, min or max across dates stay what they were;
* the ENTITY MODEL block tells the SQL writer, and the trust checks flag a written sum across dates.

On the samples warehouse with a daily stock-snapshot table beside it — three mornings across a month's end (30 and 31
March, 1 April) — every answer checked against hand-written SQL.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.models import (
    Backing,
    Binding,
    EntityProperty,
    ExpressionProperty,
    Frame,
    OntologyEntity,
    OntologyGraph,
    OntologyMetric,
    OntologyRelationship,
    SemiAdditive,
)
from aughor.ontology.semiadditive import semiadditive_problem
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
from aughor.sql.semiadditive import semiadditive_misuse

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
SNAPSHOTS = ("CREATE TABLE ecommerce.stock_snapshots AS SELECT row_number() OVER () AS snapshot_id, product_id, "
             "DATE '2026-03-30' + CAST(d AS INTEGER) AS snapshot_date, stock_quantity + CAST(d AS INTEGER) AS on_hand "
             "FROM ecommerce.products, range(0, 3) r(d)")
REFUSED = "is a reading at a moment, taken over snapshot_date"


def snapshot_type() -> OntologyEntity:
    props = {name: EntityProperty(name=name, data_type=dtype, semantic_type=role)
             for name, dtype, role in (("snapshot_id", "BIGINT", "key"), ("product_id", "VARCHAR", "dimension"),
                                       ("snapshot_date", "DATE", "timestamp"), ("on_hand", "BIGINT", "measure"))}
    return OntologyEntity(id="StockSnapshot", display_name="Stock snapshot", source_tables=["stock_snapshots"],
                          identity_key="snapshot_id", grain_verified=True, api_name="stock_snapshot", properties=props,
                          backing=Backing(kind="table", table="stock_snapshots", primary_key="snapshot_id", verified=True))


def snapshot_link() -> OntologyRelationship:
    return OntologyRelationship(
        id="StockSnapshot_RELATES_TO_Product", from_entity="StockSnapshot", to_entity="Product", verb="counts",
        cardinality="N:1", join_sql="ecommerce.stock_snapshots.product_id = ecommerce.products.product_id",
        from_table="ecommerce.stock_snapshots", from_col="product_id", to_table="ecommerce.products", to_col="product_id",
        join_confidence="verified", nullable=False, value_overlap=1.0, measured_cardinality="N:1")


def seed(path: Path) -> None:
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.execute(SNAPSHOTS)
    con.close()


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    path = tmp_path_factory.mktemp("semiadditive") / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute("SET search_path = 'ecommerce'")
    yield path, con
    con.close()


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    g.entities["StockSnapshot"] = snapshot_type()
    g.relationships["StockSnapshot_RELATES_TO_Product"] = snapshot_link()
    return g


def _declared(graph):
    graph.entities["StockSnapshot"].semiadditive = {"on_hand": SemiAdditive(over="snapshot_date",
                                                                            note="a stock count taken each morning")}
    return graph


def _run(con, graph, query):
    return sorted(tuple(r) for r in con.execute(compile_object_query(query, graph, fiscal_start_month=1).sql).fetchall())


def _hand(con, sql):
    return sorted(tuple(r) for r in con.execute(sql).fetchall())


def _sum(**kw):
    return {"object_type": "stock_snapshot", "measures": [{"name": "stock", "agg": "sum", "path": "on_hand"}], **kw}


# ── at the anchor ───────────────────────────────────────────────────────────────────────────

def test_undeclared_the_sum_across_dates_compiles_as_it_always_did(warehouse, graph):
    _, con = warehouse
    assert _run(con, graph, _sum()) == _hand(con, "SELECT SUM(on_hand) FROM stock_snapshots")


def test_declared_a_sum_across_dates_is_refused_with_how_to_ask(graph):
    with pytest.raises(ObjectQueryRefused, match=REFUSED) as refused:
        compile_object_query(_sum(), _declared(graph), fiscal_start_month=1)
    assert "a stock count taken each morning" in refused.value.reason
    assert "Group by snapshot_date, filter to one snapshot_date" in refused.value.reason


def test_every_way_of_keeping_one_date_is_answered(warehouse, graph):
    _, con = warehouse
    _declared(graph)
    assert _run(con, graph, _sum(by=["snapshot_date"])) == _hand(
        con, "SELECT snapshot_date, SUM(on_hand) FROM stock_snapshots GROUP BY 1")
    one_day = _hand(con, "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = DATE '2026-03-31'")
    assert _run(con, graph, _sum(filters=[{"path": "snapshot_date", "value": "2026-03-31"}])) == one_day
    assert _run(con, graph, _sum(filters=[{"path": "snapshot_date", "op": "in", "values": ["2026-03-31"]}])) == one_day
    own_where = {"object_type": "stock_snapshot", "measures": [
        {"name": "stock", "agg": "sum", "path": "on_hand", "where": [{"path": "snapshot_date", "value": "2026-03-31"}]}]}
    assert _run(con, graph, own_where) == one_day
    by_day = compile_object_query(_sum(grain="day"), graph, fiscal_start_month=1)
    assert sorted(r[-1] for r in con.execute(by_day.sql).fetchall()) == sorted(
        r[0] for r in con.execute("SELECT SUM(on_hand) FROM stock_snapshots GROUP BY snapshot_date").fetchall())
    assert any("a day grain on the date snapshot_date" in line for line in by_day.plan)


def test_an_average_per_date_is_a_sum_divided_by_the_dates_and_is_answered(warehouse, graph):
    _, con = warehouse
    _declared(graph)
    per_day = {"object_type": "stock_snapshot", "measures": [
        {"name": "avg_stock", "agg": "sum", "path": "on_hand",
         "divide_by": {"agg": "count_distinct", "path": "snapshot_date"}}]}
    (got,), = _run(con, graph, per_day)
    (want,), = _hand(con, "SELECT SUM(on_hand) * 1.0 / COUNT(DISTINCT snapshot_date) FROM stock_snapshots")
    assert got == pytest.approx(want)


def test_one_snapshot_by_its_key_is_answered_as_its_object_page_asks(warehouse, graph):
    _, con = warehouse
    _declared(graph)
    graph.metrics["stock_level"] = OntologyMetric(id="stock_level", display_name="Stock level", entity="StockSnapshot",
                                                  formula_sql="SUM(on_hand)", verified=True)
    page = {"object_type": "stock_snapshot", "filters": [{"path": "snapshot_id", "value": 5}],
            "measures": [{"name": "value", "metric": "stock_level"}]}
    assert _run(con, graph, page) == _hand(con, "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_id = 5")


MONTH_END = ("SELECT SUM(on_hand) FROM stock_snapshots s WHERE snapshot_date = (SELECT {edge}(snapshot_date) "
             "FROM stock_snapshots t WHERE DATE_TRUNC('month', t.snapshot_date) = DATE_TRUNC('month', s.snapshot_date)) "
             "GROUP BY DATE_TRUNC('month', snapshot_date)")


def _taking(graph, take):
    graph.entities["StockSnapshot"].semiadditive = {"on_hand": SemiAdditive(over="snapshot_date", take=take)}
    return graph


def test_a_declared_month_end_is_each_months_last_reading(warehouse, graph):
    _, con = warehouse
    _taking(graph, "last")
    monthly = compile_object_query(_sum(grain="month"), graph, fiscal_start_month=1)
    assert sorted(r[-1] for r in con.execute(monthly.sql).fetchall()) == sorted(
        r[0] for r in con.execute(MONTH_END.format(edge="MAX")).fetchall())          # 31 March, then 1 April
    assert any("summed at each group's last snapshot_date (declared take: last)" in line for line in monthly.plan)
    assert _run(con, graph, _sum()) == _hand(con, "SELECT SUM(on_hand) FROM stock_snapshots "
                                                  "WHERE snapshot_date = DATE '2026-04-01'")
    assert _run(con, graph, _sum(start="2026-03-01", end="2026-04-01")) == _hand(
        con, "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = DATE '2026-03-31'")   # the window's last
    before_april = {"object_type": "stock_snapshot", "measures": [{"name": "stock", "agg": "sum", "path": "on_hand",
                    "where": [{"path": "snapshot_date", "op": "<", "value": "2026-04-01"}]}]}
    assert _run(con, graph, before_april) == _hand(                          # the last among the rows it reads
        con, "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = DATE '2026-03-31'")
    assert _run(con, graph, _sum(by=["product_id"])) == _hand(
        con, "SELECT product_id, SUM(on_hand) FROM stock_snapshots s WHERE snapshot_date = (SELECT MAX(snapshot_date) "
             "FROM stock_snapshots t WHERE t.product_id = s.product_id) GROUP BY 1")
    graph.metrics["stock_level"] = OntologyMetric(id="stock_level", display_name="Stock level", entity="StockSnapshot",
                                                  formula_sql="SUM(on_hand)", verified=True)
    by_metric = compile_object_query({"object_type": "stock_snapshot", "grain": "month",
                                      "measures": [{"name": "s", "metric": "stock_level"}]}, graph, fiscal_start_month=1)
    assert sorted(r[-1] for r in con.execute(by_metric.sql).fetchall()) == sorted(
        r[0] for r in con.execute(MONTH_END.format(edge="MAX")).fetchall())


def test_a_declared_first_reading_is_each_months_opening(warehouse, graph):
    _, con = warehouse
    _taking(graph, "first")
    monthly = compile_object_query(_sum(grain="month"), graph, fiscal_start_month=1)
    assert sorted(r[-1] for r in con.execute(monthly.sql).fetchall()) == sorted(
        r[0] for r in con.execute(MONTH_END.format(edge="MIN")).fetchall())          # 30 March, then 1 April


def test_a_period_reading_is_never_found_across_connections(graph):
    from aughor.semantic.object_query import ObjectQuery, _Compiler
    compiler = _Compiler(_taking(graph, "last"), ObjectQuery.model_validate(_sum()), "duckdb", 1)
    compiler.far = {"x": object()}                  # as ON-8 compiles a read by key from another connection
    compiler._period_specs = [("pr1", "t0.snapshot_date", "last", "")]
    with pytest.raises(ObjectQueryRefused, match="reads another connection by key"):
        compiler.period_joins("stock_snapshots AS t0", "", [])


def test_without_take_a_month_is_refused_with_how_to_declare_one(graph):
    with pytest.raises(ObjectQueryRefused, match=r"declare which reading stands for a period \(take: last"):
        compile_object_query(_sum(grain="month"), _declared(graph), fiscal_start_month=1)
    snap = _taking(graph, "last").entities["StockSnapshot"]
    assert semiadditive_problem(graph, snap, "on_hand", {"over": "snapshot_date", "take": "middle"}).startswith(
        "`take` names which reading stands for a period")
    with pytest.raises(ObjectQueryRefused, match="through a link"):   # a period's reading is the declaring type's own
        compile_object_query({"object_type": "product", "measures": [
            {"name": "s", "agg": "sum", "path": "product_to_stock_snapshot.on_hand"}]}, graph, fiscal_start_month=1)


def test_what_only_looks_like_one_date_is_refused(graph):
    _declared(graph)
    for looks_like_one in (
            # a comparison with another property: each row with its own date, never one date
            _sum(filters=[{"path": "snapshot_date", "op": "=", "value_path": "snapshot_date"}]),
            _sum(filters=[{"path": "snapshot_date", "op": "in", "values": ["2026-03-30", "2026-03-31"]}]),
            _sum(filters=[{"path": "snapshot_date", "op": "!=", "value": "2026-03-30"}]),
            _sum(grain="month"),
            _sum(by=["product_id"]),
            {"object_type": "stock_snapshot", "measures": [
                {"name": "x", "agg": "sum", "path": "on_hand",
                 "divide_by": {"agg": "count_distinct", "path": "product_id"}}]}):
        with pytest.raises(ObjectQueryRefused, match=REFUSED):
            compile_object_query(looks_like_one, graph, fiscal_start_month=1)
    snap = graph.entities["StockSnapshot"]           # a day of a TIMESTAMP holds as many readings as were taken in it
    snap.properties["counted_at"] = EntityProperty(name="counted_at", data_type="TIMESTAMP", semantic_type="timestamp")
    snap.semiadditive["on_hand"] = SemiAdditive(over="counted_at")
    with pytest.raises(ObjectQueryRefused, match="is a reading at a moment, taken over counted_at"):
        compile_object_query(_sum(grain="day", time="counted_at"), graph, fiscal_start_month=1)


def test_an_average_min_or_max_across_dates_is_still_answered(warehouse, graph):
    _, con = warehouse
    _declared(graph)
    for agg in ("avg", "min", "max"):
        got = _run(con, graph, {"object_type": "stock_snapshot", "measures": [{"agg": agg, "path": "on_hand"}]})
        assert got == _hand(con, f"SELECT {agg.upper()}(on_hand) FROM stock_snapshots"), agg


def test_a_metric_that_sums_it_is_held_to_the_same_law(warehouse, graph):
    _, con = warehouse
    _declared(graph)
    graph.metrics["stock_level"] = OntologyMetric(id="stock_level", display_name="Stock level", entity="StockSnapshot",
                                                  formula_sql="SUM(on_hand)", verified=True)
    metric = {"object_type": "stock_snapshot", "measures": [{"name": "s", "metric": "stock_level"}]}
    with pytest.raises(ObjectQueryRefused, match="metric stock_level: StockSnapshot.on_hand is a reading at a moment"):
        compile_object_query(metric, graph, fiscal_start_month=1)
    assert _run(con, graph, {**metric, "by": ["snapshot_date"]}) == _hand(
        con, "SELECT snapshot_date, SUM(on_hand) FROM stock_snapshots GROUP BY 1")
    graph.metrics["avg_stock"] = OntologyMetric(id="avg_stock", display_name="Average stock", entity="StockSnapshot",
                                                formula_sql="SUM(on_hand) / COUNT(DISTINCT snapshot_date)", verified=True)
    (got,), = _run(con, graph, {"object_type": "stock_snapshot", "measures": [{"name": "a", "metric": "avg_stock"}]})
    assert got == pytest.approx(_hand(con, "SELECT SUM(on_hand) / COUNT(DISTINCT snapshot_date) FROM stock_snapshots")[0][0])


def test_a_formula_that_reads_it_is_a_reading_too(warehouse, graph):
    _, con = warehouse
    snap = _declared(graph).entities["StockSnapshot"]
    snap.expressions["stock_units_x2"] = ExpressionProperty(expression="on_hand * 2", verified=True)
    snap.properties["stock_units_x2"] = snap.expressions["stock_units_x2"].as_property("stock_units_x2")
    across = {"object_type": "stock_snapshot", "measures": [{"name": "v", "agg": "sum", "path": "stock_units_x2"}]}
    with pytest.raises(ObjectQueryRefused, match="StockSnapshot.stock_units_x2 reads StockSnapshot.on_hand, which is a "
                                                 "reading at a moment"):
        compile_object_query(across, graph, fiscal_start_month=1)
    assert _run(con, graph, {**across, "by": ["snapshot_date"]}) == _hand(
        con, "SELECT snapshot_date, SUM(on_hand * 2) FROM stock_snapshots GROUP BY 1")


# ── through a link, over readings, in a frame ───────────────────────────────────────────────

def test_a_sum_through_a_link_is_refused_and_an_average_is_not(warehouse, graph):
    _, con = warehouse
    _declared(graph)
    through = {"object_type": "product", "measures": [{"name": "s", "agg": "sum",
                                                        "path": "product_to_stock_snapshot.on_hand"}]}
    with pytest.raises(ObjectQueryRefused, match="a sum of it through a link adds readings from many moments"):
        compile_object_query(through, graph, fiscal_start_month=1)
    through["measures"][0]["agg"] = "avg"
    (got,), = _run(con, graph, through)
    assert got == pytest.approx(_hand(con, "SELECT AVG(on_hand) FROM stock_snapshots")[0][0])


def _history(**frames) -> Binding:
    props = {"on_hand": EntityProperty(name="on_hand", data_type="BIGINT", semantic_type="measure"),
             "snapshot_date": EntityProperty(name="snapshot_date", data_type="DATE", semantic_type="timestamp")}
    props.update({name: EntityProperty(name=name, data_type="DOUBLE", semantic_type="measure") for name in frames})
    return Binding(name="stock_history", kind="timeseries", table="stock_snapshots", key="product_id",
                   time_column="snapshot_date", properties=props, frames=frames, verified=True, rows=450, objects=150,
                   covered=150, orphans=0)


def _declared_on_product(graph, **frames):
    product = graph.entities["Product"]
    product.bindings = [_history(**frames)]
    product.semiadditive = {"on_hand": SemiAdditive(over="snapshot_date")}
    return graph


def test_the_latest_reading_sums_across_objects_and_its_history_does_not(warehouse, graph):
    _, con = warehouse
    _declared_on_product(graph)
    latest = {"object_type": "product", "measures": [{"name": "s", "agg": "sum", "path": "on_hand"}]}
    assert _run(con, graph, latest) == _hand(con, "SELECT SUM(on_hand) FROM stock_snapshots s WHERE snapshot_date = ("
                                                  "SELECT MAX(snapshot_date) FROM stock_snapshots t "
                                                  "WHERE t.product_id = s.product_id)")
    history = {"object_type": "product", "measures": [{"name": "s", "agg": "sum", "path": "stock_history.on_hand"}]}
    with pytest.raises(ObjectQueryRefused, match="the readings of stock_history are many moments per Product"):
        compile_object_query(history, graph, fiscal_start_month=1)
    history["measures"][0]["where"] = [{"path": "snapshot_date", "value": "2026-03-31"}]
    assert _run(con, graph, history) == _hand(
        con, "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = DATE '2026-03-31'")
    history["measures"][0] = {"name": "a", "agg": "avg", "path": "stock_history.on_hand"}
    (got,), = _run(con, graph, history)
    assert got == pytest.approx(_hand(con, "SELECT AVG(on_hand) FROM stock_snapshots")[0][0])


def test_a_frame_that_sums_the_readings_is_refused_and_an_average_frame_is_not(warehouse, graph):
    _, con = warehouse
    _declared_on_product(graph, on_hand_3=Frame(column="on_hand", agg="sum", range="trailing", window=3))
    framed = {"object_type": "product", "measures": [{"name": "x", "agg": "max", "path": "on_hand_3"}]}
    with pytest.raises(ObjectQueryRefused, match="Declare the frame an avg, min or max"):
        compile_object_query(framed, graph, fiscal_start_month=1)
    _declared_on_product(graph, on_hand_3=Frame(column="on_hand", agg="avg", range="trailing", window=3))
    (got,), = _run(con, graph, framed)
    assert got == pytest.approx(_hand(con, "SELECT MAX(a) FROM (SELECT product_id, AVG(on_hand) AS a "
                                           "FROM stock_snapshots GROUP BY 1)")[0][0])


# ── the declaration ─────────────────────────────────────────────────────────────────────────

def test_the_declaration_is_checked_against_the_graph(graph):
    snap = graph.entities["StockSnapshot"]
    assert semiadditive_problem(graph, snap, "on_hand", {"over": "snapshot_date"}) == ""
    assert "not a date or timestamp" in semiadditive_problem(graph, snap, "on_hand", {"over": "product_id"})
    assert "name the time property" in semiadditive_problem(graph, snap, "on_hand", {"over": ""})
    assert "no property 'on_hnd'" in semiadditive_problem(graph, snap, "on_hnd", {"over": "snapshot_date"})
    assert "itself a moment" in semiadditive_problem(graph, snap, "snapshot_date", {"over": "snapshot_date"})
    assert semiadditive_problem(graph, snap, "on_hand", {"over": "stock_snapshot_to_product.product_id"}) == (
        "`over` must be StockSnapshot's own time property — 'stock_snapshot_to_product.product_id' is reached "
        "through a link")


def test_the_overlay_applies_a_bound_declaration_and_never_a_stale_one(graph):
    from aughor.ontology.overrides import OntologyOverride, save_override
    save_override("c27", "main", OntologyOverride(
        target_kind="entity", target_id="StockSnapshot",
        fields={"semiadditive": {"on_hand": {"over": "snapshot_date", "note": ""}}},
        binding={"semiadditive": {"on_hand": {"bound": True, "note": "", "over": "snapshot_date"}}}))
    served, _ = OV.apply_overrides(graph, "c27", "main")
    assert served.entities["StockSnapshot"].semiadditive["on_hand"].over == "snapshot_date"
    save_override("c27", "main", OntologyOverride(
        target_kind="entity", target_id="StockSnapshot",
        fields={"semiadditive": {"on_hand": {"over": "snapshot_date", "note": "", "take": "last"}}},
        binding={"semiadditive": {"on_hand": {"bound": True, "note": "", "over": "snapshot_date"}}}))
    fresh = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    fresh.entities["StockSnapshot"] = snapshot_type()
    served, _ = OV.apply_overrides(fresh, "c27", "main")
    assert served.entities["StockSnapshot"].semiadditive["on_hand"].take == "last"
    save_override("c27", "main", OntologyOverride(
        target_kind="entity", target_id="StockSnapshot",
        fields={"semiadditive": {"on_hand": {"over": "snapshot_date", "note": ""}}},
        binding={"semiadditive": {"on_hand": {"bound": True, "note": "", "over": "another_date"}}}))
    fresh = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    fresh.entities["StockSnapshot"] = snapshot_type()
    stale, _ = OV.apply_overrides(fresh, "c27", "main")
    assert stale.entities["StockSnapshot"].semiadditive == {}


# ── the SQL writer's side ───────────────────────────────────────────────────────────────────

def test_the_sql_writer_is_told_in_the_entity_model(graph):
    from aughor.ontology.builder import render_ontology_annotations
    assert "READING AT A MOMENT" not in render_ontology_annotations(graph)
    block = render_ontology_annotations(_declared(graph))
    assert ("READING AT A MOMENT: on_hand, taken over snapshot_date (a stock count taken each morning) — SUM it only "
            "within one snapshot_date") in block
    assert "a period's figure" not in block
    assert ("a period's figure (a month's) is the total at its last snapshot_date — WHERE snapshot_date IN (SELECT "
            "MAX(snapshot_date)") in render_ontology_annotations(_taking(graph, "last"))


DECLARED = {"stock_snapshots": {"on_hand": {"over": "snapshot_date", "note": ""}}}
DAILY = "WITH daily AS (SELECT snapshot_date, SUM(on_hand) AS total FROM stock_snapshots GROUP BY 1) "
FLAGGED = (
    "SELECT SUM(on_hand) FROM stock_snapshots",
    "SELECT product_id, SUM(on_hand) FROM stock_snapshots GROUP BY 1",
    "SELECT SUM(s.on_hand) FROM stock_snapshots s JOIN products p ON p.product_id = s.product_id",
    "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = '2026-03-30' OR snapshot_date = '2026-03-31'",
    "SELECT SUM(on_hand) FROM stock_snapshots WHERE NOT snapshot_date = '2026-03-30'",
    "SELECT SUM(s.on_hand) FROM stock_snapshots s JOIN stock_snapshots t ON t.snapshot_id = s.snapshot_id "
    "WHERE s.snapshot_date = t.snapshot_date",
    "SELECT SUM(s.on_hand) FROM stock_snapshots s JOIN stock_snapshots t ON t.snapshot_id = s.snapshot_id "
    "WHERE s.snapshot_date = CAST(t.snapshot_date AS DATE)",          # a value that is another row's, not one
    "SELECT SUM(on_hand) / COUNT(DISTINCT product_id) FROM stock_snapshots",
    "SELECT DATE_TRUNC('month', snapshot_date) AS m, SUM(on_hand) FROM stock_snapshots GROUP BY 1",
    # every month's end, added together
    "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date IN (SELECT MAX(snapshot_date) FROM stock_snapshots "
    "GROUP BY DATE_TRUNC('month', snapshot_date))",
    # through an intermediate query: daily totals summed across days — the moment carried, or not
    DAILY + "SELECT SUM(total) FROM daily",
    DAILY + "SELECT SUM(d.total) FROM daily d JOIN products p ON TRUE WHERE p.product_id = 'P001'",
    "SELECT SUM(t) FROM (SELECT SUM(on_hand) AS t FROM stock_snapshots GROUP BY snapshot_date) d",
    "WITH s AS (SELECT * FROM stock_snapshots) SELECT product_id, SUM(on_hand) FROM s GROUP BY 1",
    "WITH v AS (SELECT snapshot_date AS d, on_hand * 2 AS units FROM stock_snapshots) SELECT SUM(units) FROM v",
    "WITH a AS (SELECT * FROM stock_snapshots), b AS (SELECT snapshot_date, SUM(on_hand) AS t FROM a GROUP BY 1) "
    "SELECT SUM(t) FROM b",
    # a window beside the readings does not make them one moment
    "WITH x AS (SELECT *, SUM(on_hand) OVER (PARTITION BY product_id) AS product_total FROM stock_snapshots) "
    "SELECT SUM(on_hand) FROM x",
)
SILENT = (
    "SELECT snapshot_date, SUM(on_hand) FROM stock_snapshots GROUP BY snapshot_date",
    "SELECT snapshot_date, SUM(on_hand) FROM stock_snapshots GROUP BY 1",
    "SELECT snapshot_date AS d, SUM(on_hand) FROM stock_snapshots GROUP BY d",
    "SELECT snapshot_date, SUM(on_hand) FROM stock_snapshots GROUP BY ALL",
    "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = '2026-03-31'",
    "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date IN ('2026-03-31')",
    "SELECT SUM(on_hand) FROM stock_snapshots WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM stock_snapshots)",
    "SELECT SUM(on_hand) / COUNT(DISTINCT snapshot_date) FROM stock_snapshots",
    "SELECT 1.0 * SUM(on_hand) / NULLIF(COUNT(DISTINCT snapshot_date), 0) FROM stock_snapshots",
    "SELECT AVG(on_hand), MIN(on_hand), MAX(on_hand) FROM stock_snapshots",
    "SELECT SUM(stock_quantity) FROM products",
    "SELECT snapshot_date, SUM(on_hand) OVER (PARTITION BY snapshot_date) FROM stock_snapshots",
    # a month-end: each month's last reading, per month — uncorrelated and correlated
    "SELECT DATE_TRUNC('month', snapshot_date) AS m, SUM(on_hand) FROM stock_snapshots WHERE snapshot_date IN "
    "(SELECT MAX(snapshot_date) FROM stock_snapshots GROUP BY DATE_TRUNC('month', snapshot_date)) GROUP BY 1",
    "SELECT DATE_TRUNC('month', s.snapshot_date) AS m, SUM(s.on_hand) FROM stock_snapshots s WHERE s.snapshot_date = "
    "(SELECT MAX(t.snapshot_date) FROM stock_snapshots t WHERE DATE_TRUNC('month', t.snapshot_date) = "
    "DATE_TRUNC('month', s.snapshot_date)) GROUP BY 1",
    # through an intermediate query, kept to one moment or averaged
    DAILY + "SELECT AVG(total) FROM daily",
    DAILY + "SELECT snapshot_date, SUM(total) FROM daily GROUP BY 1",
    DAILY + "SELECT SUM(total) FROM daily WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM daily)",
    DAILY + "SELECT SUM(total) / COUNT(DISTINCT snapshot_date) FROM daily",
    "SELECT SUM(t) / COUNT(*) FROM (SELECT SUM(on_hand) AS t FROM stock_snapshots GROUP BY snapshot_date) d",
    "WITH s AS (SELECT * FROM stock_snapshots WHERE snapshot_date = '2026-03-31') SELECT SUM(on_hand) FROM s",
    # the latest reading per product, then summed: one moment per product
    "SELECT SUM(on_hand) FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY snapshot_date DESC) AS rn "
    "FROM stock_snapshots) x WHERE rn = 1",
    "SELECT SUM(on_hand) FROM (SELECT product_id, on_hand FROM stock_snapshots QUALIFY ROW_NUMBER() OVER ("
    "PARTITION BY product_id ORDER BY snapshot_date DESC) = 1) x",
    "WITH d AS (SELECT snapshot_date, AVG(on_hand) AS a FROM stock_snapshots GROUP BY 1) SELECT SUM(a) FROM d",
    # a change since the last reading is a flow: its sum across days is the net change
    "WITH c AS (SELECT snapshot_date, on_hand - LAG(on_hand) OVER (PARTITION BY product_id ORDER BY snapshot_date) "
    "AS change FROM stock_snapshots) SELECT SUM(change) FROM c",
)


def test_the_trust_checks_flag_a_written_sum_across_dates_and_nothing_within_one(warehouse):
    _, con = warehouse
    for sql in FLAGGED + SILENT:
        con.execute(sql).fetchall()                         # every statement here is one the warehouse runs
    for sql in FLAGGED:
        hit = semiadditive_misuse(sql, DECLARED)
        assert hit is not None and "a reading at a moment taken over" in hit[1] and "snapshot_date" in hit[1], sql
    for sql in SILENT:
        assert semiadditive_misuse(sql, DECLARED) is None, sql


def test_a_statement_whose_scopes_cannot_be_built_is_still_read_flat(monkeypatch):
    import sqlglot.optimizer.scope as scope

    def unbuildable(_tree):
        raise ValueError("a shape the scope builder does not know")
    monkeypatch.setattr(scope, "traverse_scope", unbuildable)
    assert semiadditive_misuse("SELECT SUM(on_hand) FROM stock_snapshots", DECLARED) is not None
    assert semiadditive_misuse("SELECT snapshot_date, SUM(on_hand) FROM stock_snapshots GROUP BY 1", DECLARED) is None


def test_the_trust_checks_read_the_declaration_through_the_registry(monkeypatch):
    from aughor.kernel.registries import readings as R
    from aughor.sql.trust_checks import run_trust_checks
    sql = "SELECT SUM(on_hand) FROM stock_snapshots"
    monkeypatch.setattr(R, "_loader", lambda conn: DECLARED if conn == "c27" else {})
    (issue,) = [t for t in run_trust_checks(sql, connection_id="c27") if t.pattern == "semiadditive-sum"]
    assert issue.subject == "stock_snapshots.on_hand"
    assert not [t for t in run_trust_checks(sql, connection_id="another") if t.pattern == "semiadditive-sum"]
    assert not [t for t in run_trust_checks(sql) if t.pattern == "semiadditive-sum"]
    monkeypatch.setattr(R, "_loader", None)                 # a bare platform declares nothing
    assert not [t for t in run_trust_checks(sql, connection_id="c27") if t.pattern == "semiadditive-sum"]


# ── the door, over HTTP ─────────────────────────────────────────────────────────────────────

CONN = "semiadditive-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def door(tmp_path, monkeypatch):
    """A cached graph for CONN/ecommerce (with the StockSnapshot type), an empty overrides tree, and a warehouse of its
    own every opener resolves to — never the module's, which this process holds open."""
    import aughor.db.connection as C
    from aughor.db.connection import open_connection
    from aughor.ontology import store as ST
    from aughor.ontology.semiadditive import forget_declared
    from aughor.util.json_store import KeyedJsonStore
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    g.entities["StockSnapshot"] = snapshot_type()
    ST.save_ontology(CONN, "ecommerce", "fp", g)
    path = tmp_path / "samples.duckdb"
    seed(path)
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda *_a, **_k: open_connection(
        "duckdb", str(path), schema_name="ecommerce", connection_id=CONN))
    forget_declared(CONN)
    yield
    forget_declared(CONN)


def test_declared_and_withdrawn_over_http_and_the_trust_checks_follow_at_once(door, client):
    from aughor.sql.trust_checks import run_trust_checks

    def flagged():
        return [t.pattern for t in run_trust_checks("SELECT SUM(on_hand) FROM stock_snapshots", connection_id=CONN)
                if t.pattern == "semiadditive-sum"]
    url = "/ontology/entities/StockSnapshot/semiadditive/on_hand"
    assert flagged() == []
    bad = client.put(url, params=PARAMS, json={"over": "product_id"})
    assert bad.status_code == 400 and "not a date or timestamp" in bad.json()["detail"]
    assert client.put("/ontology/entities/Nope/semiadditive/on_hand", params=PARAMS,
                      json={"over": "snapshot_date"}).status_code == 404
    ok = client.put(url, params=PARAMS, json={"over": "snapshot_date", "note": "counted each morning"})
    assert ok.status_code == 200, ok.text
    query = {"object_type": "stock_snapshot", "measures": [{"name": "s", "agg": "sum", "path": "on_hand"}]}
    refused = client.post("/objects/query", params={**PARAMS, "execute": "false"}, json=query).json()
    assert refused["path"] == "refused" and "counted each morning" in refused["refused"]
    assert flagged() == ["semiadditive-sum"]
    assert client.delete(url, params=PARAMS).status_code == 200
    assert client.post("/objects/query", params={**PARAMS, "execute": "false"}, json=query).json()["path"] == "compiled"
    assert flagged() == []                                  # the withdrawal reaches the checks now, not in 30s
    assert client.delete(url, params=PARAMS).status_code == 404
