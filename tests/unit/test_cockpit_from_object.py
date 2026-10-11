"""Starting a cockpit from an object (2026-10-10; design-mockups/cockpit-from-object.html).

What the starter offers is read from the served ontology and measured through the object door before it is offered.
Every figure and preview here is held to a hand-written query over the seeded samples warehouse: the count, a money
figure (averaged where its sum would mean nothing — a price per unit, a price of a thing that simply exists), each
filter's values and counts, and the chart's daily counts over the last days the objects hold. A category that picks
out single objects, a property the reader may not read, and an action declared on another object are never offered.
The three pieces it adds are checked like every piece bound to the ontology before a cockpit is kept.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from aughor.cockpit import from_object as FO
from aughor.cockpit import pieces
from aughor.db.connection import open_connection
from aughor.ontology.models import OntologyGraph
from aughor.semantic.object_query import compile_object_query
from tests.unit.test_cockpit_pieces import _graph as _pieces_graph
from tests.unit.test_object_bindings import GRAPH, seed

TODAY = date(2026, 10, 10)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("from-object") / "samples.duckdb"
    seed(path)
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="from-object-t")
    yield conn
    conn.close()


def _graph() -> OntologyGraph:
    """The samples' graph with two declared actions — "flag for review" on Order, "hold customer" on Customer — as the
    cockpit pieces' suite declares them."""
    return _pieces_graph()


def _runner(db, graph, asked: list | None = None):
    def run(query: dict):
        if asked is not None:
            asked.append(query)
        compiled = compile_object_query(query, graph)
        result = db.execute("reference", compiled.sql)
        if result.error:
            raise RuntimeError(result.error)
        return list(result.columns or compiled.columns), list(result.rows or []), list(compiled.caveats)
    return run


def hand(db, sql: str) -> list[tuple]:
    result = db.execute("reference", sql)
    assert not result.error, (result.error, sql)
    return [tuple(row) for row in result.rows]          # cells are text


def number(db, sql: str) -> float:
    return float(hand(db, sql)[0][0])


@pytest.fixture
def order(db):
    g = _graph()
    return FO.propose(g, "order", _runner(db, g), today=TODAY)


# ── what is offered, held to the warehouse ────────────────────────────────────────────────────

def test_the_count_and_each_figure_are_the_warehouse_s(order, db):
    assert order["title"] == "Orders" and order["total"] == number(db, "SELECT count(*) FROM ecommerce.orders")
    by = {f["label"]: f for f in order["figures"]}
    assert by["Orders"]["value"] == order["total"] and by["Orders"]["agg"] == "count"
    assert by["Average item count"]["value"] == pytest.approx(number(db, "SELECT avg(item_count) FROM ecommerce.orders"))


def test_a_price_per_unit_is_averaged_never_summed(order, db):
    """`total_amount` is profiled per unit here; its sum counts one unit per row, which the door warns of — so the
    starter offers its average, on an object that has a date and would otherwise be summed."""
    [money] = [f for f in order["figures"] if f["format"] == "money"]
    assert money["agg"] == "avg" and money["label"] == "Average total amount"
    assert money["value"] == pytest.approx(number(db, "SELECT avg(total_amount) FROM ecommerce.orders"))


def test_money_on_an_object_with_no_date_is_averaged(db):
    g = _graph()
    products = FO.propose(g, "product", _runner(db, g), today=TODAY)
    assert products["chart"] is None
    [money] = [f for f in products["figures"] if f["format"] == "money"]
    assert money["agg"] == "avg"


def test_each_filter_s_values_and_counts_are_the_warehouse_s(order, db):
    status = next(f for f in order["filters"] if f["path"] == "status")
    rows = hand(db, "SELECT status, count(*) AS n FROM ecommerce.orders GROUP BY status ORDER BY n DESC, status")
    assert {(str(v), n) for v, n in status["values"]} == {(str(v), float(n)) for v, n in rows[:FO.PREVIEW_VALUES]}
    counts = [n for _, n in status["values"]]
    assert counts == sorted(counts, reverse=True)


def test_the_object_s_own_categories_come_first_and_one_through_a_link_second(order):
    paths = [f["path"] for f in order["filters"]]
    assert len(paths) <= FO.MAX_FILTERS and paths[0] == "status"
    linked = [f for f in order["filters"] if f["via"]]
    assert len(linked) == 1 and paths.index(linked[0]["path"]) == 1 and "." in linked[0]["path"]
    assert linked[0]["via"] == "Customer"


def test_the_chart_counts_each_of_the_last_whole_days_the_objects_hold(order, db):
    chart = order["chart"]
    [last] = hand(db, "SELECT max(order_date) FROM ecommerce.orders")[0]
    assert chart["end"] == FO.window_end(date.fromisoformat(str(last)[:10]), TODAY).isoformat()
    n = number(db, f"SELECT count(*) FROM ecommerce.orders WHERE order_date >= DATE '{chart['end']}' - INTERVAL 30 DAY "
                   f"AND order_date < DATE '{chart['end']}'")
    assert len(chart["bars"]) == FO.CHART_DAYS and sum(chart["bars"]) == n > 0


def test_a_window_ends_today_unless_the_objects_stop_before_it():
    assert FO.window_end(date(2026, 10, 12), TODAY) == TODAY                  # rows dated ahead of today
    assert FO.window_end(date(2024, 12, 30), TODAY) == date(2024, 12, 31)     # an old dataset
    assert FO.window_end(None, TODAY) == TODAY


def test_the_table_lists_what_the_filters_and_figures_read(order):
    cols = order["table"]["columns"]
    assert len(cols) <= FO.MAX_TABLE_COLUMNS and cols[0] == "status" and cols[1] == "order_date"
    labels = dict(zip(cols, order["table"]["labels"]))
    assert len(labels) == len(cols)
    # each column is named as its property is: `item_count` is also averaged as a figure, and stays "Item Count"
    assert labels["item_count"] == "Item Count" and labels["order_date"] == "Order Date"


def test_only_the_actions_declared_on_this_object_are_offered(order):
    assert order["actions"] == [{"id": "flag_for_review", "label": "flag for review"}]


# ── what is never offered ─────────────────────────────────────────────────────────────────────

def test_a_property_the_reader_may_not_read_is_never_offered(db, monkeypatch):
    monkeypatch.setattr("aughor.ontology.security.masked",
                        lambda entity, prop, who=None: "masked" if prop == "status" else None)
    g = _graph()
    asked: list = []
    out = FO.propose(g, "order", _runner(db, g, asked), today=TODAY)
    assert "status" not in [f["path"] for f in out["filters"]] + out["table"]["columns"]
    assert not any("status" in json.dumps(q) for q in asked)


def test_a_property_read_through_a_link_the_reader_may_not_read_is_never_offered(db, monkeypatch):
    monkeypatch.setattr("aughor.ontology.security.masked",
                        lambda entity, prop, who=None: "masked" if entity.id == "Customer" else None)
    g = _graph()
    asked: list = []
    out = FO.propose(g, "order", _runner(db, g, asked), today=TODAY)
    assert not [f for f in out["filters"] if f["via"]]
    # not offered, and not asked about either: the compiler would refuse it, but a refused query is still a probe
    assert not any("order_to_customer." in json.dumps(q) for q in asked)


def test_a_category_that_picks_out_single_objects_is_not_a_filter(db):
    """Each value held by fewer than two objects on average: a lookup, not a filter — though it has few values."""
    g = _graph()
    real = _runner(db, g)

    def run(query: dict):
        cols, rows, said = real(query)
        if any(m.get("agg") == "count_distinct" for m in query["measures"]):
            row = list(rows[0])
            row[cols.index("n")], row[cols.index("d0")] = 30, 20    # status: 20 values over 30 objects — under the cap
            rows = [row]
        return cols, rows, said
    out = FO.propose(g, "order", run, today=TODAY)
    assert "status" not in [f["path"] for f in out["filters"]]


def test_one_refused_measure_does_not_take_the_others_with_it(db):
    g = _graph()
    got, _ = FO._measured(_runner(db, g), "order", [{"name": "n", "agg": "count"},
                                                    {"name": "x", "agg": "sum", "path": "no_such_property"}])
    assert set(got) == {"n"}


def test_the_plural_of_a_name():
    assert [FO.plural(w) for w in ("Order", "Category", "Address", "Day", "Box")] == [
        "Orders", "Categories", "Addresses", "Days", "Boxes"]


# ── the door ──────────────────────────────────────────────────────────────────────────────────

CONN = "from-object-door-t"
ON = {"cockpit.composed", "ontology.cockpit_pieces", "ontology.object_cockpits"}


@pytest.fixture
def door(tmp_path, monkeypatch):
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.routers._shared import invalidate_schema_cache
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", OntologyGraph.model_validate(json.loads(GRAPH.read_text())))
    path = tmp_path / "samples.duckdb"
    seed(path)
    invalidate_schema_cache(CONN)
    monkeypatch.setattr(C, "open_connection_for_with_schema",
                        lambda *_a, **_k: open_connection("duckdb", str(path), schema_name="ecommerce",
                                                          connection_id=CONN))


def _flags(monkeypatch, on: set) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name in on)


def test_the_door_offers_a_cockpit_measured_on_the_warehouse(door, client, monkeypatch):
    _flags(monkeypatch, ON)
    res = client.get("/cockpits/from-object", params={"entity": "order", "connection_id": CONN,
                                                      "schema_name": "ecommerce"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["entity"] == "order" and body["total"] == 5000 and body["filters"] and body["chart"]


def test_the_door_is_shut_while_its_flag_is_off(door, client, monkeypatch):
    _flags(monkeypatch, ON - {"ontology.object_cockpits"})
    res = client.get("/cockpits/from-object", params={"entity": "order", "connection_id": CONN})
    assert res.status_code == 404 and "off" in res.json()["detail"]


def test_an_object_that_does_not_exist_is_refused_with_the_names_that_do(door, client, monkeypatch):
    _flags(monkeypatch, ON)
    res = client.get("/cockpits/from-object", params={"entity": "shipment", "connection_id": CONN,
                                                      "schema_name": "ecommerce"})
    assert res.status_code == 422
    assert "order" in res.json()["detail"]["available"]


# ── the three pieces, as the server holds them ────────────────────────────────────────────────

def _spec(**els) -> dict:
    elements = {"cockpit": {"type": "Cockpit", "props": {"title": "Orders"}, "children": ["sec"]},
                "sec": {"type": "Section", "props": {"title": "Orders"}, "children": list(els)}}
    elements.update(els)
    return {"root": "cockpit", "elements": elements}


FILTERS = {"type": "ObjectFilters", "props": {"entity": "order", "properties": [{"path": "status", "label": "Status"}]},
           "children": []}
FIGURE = {"type": "ObjectFigure", "props": {"entity": "order", "label": "Orders", "agg": "count"}, "children": []}
CHART = {"type": "ObjectChart", "props": {"entity": "order", "label": "Orders per day", "time": "order_date"},
         "children": []}


@pytest.fixture
def no_edits(monkeypatch):
    monkeypatch.setattr(pieces, "accepted_edits", lambda conn: [])


def test_the_three_pieces_are_refused_while_their_flag_is_off(monkeypatch, no_edits):
    _flags(monkeypatch, {"ontology.cockpit_pieces"})
    [said] = pieces.not_resolved("c", _spec(f=FILTERS, g=FIGURE, h=CHART), graph=_graph())
    assert "3 filter column, figure or chart piece(s)" in said and "off on this install" in said


def test_the_three_pieces_keep_when_every_query_they_make_compiles(monkeypatch, no_edits):
    _flags(monkeypatch, ON)
    assert pieces.not_resolved("c", _spec(f=FILTERS, g=FIGURE, h=CHART), graph=_graph()) == []


def test_a_piece_naming_what_the_object_does_not_hold_is_refused_in_the_compiler_s_words(monkeypatch, no_edits):
    _flags(monkeypatch, ON)
    bad = {"type": "ObjectFilters", "props": {"entity": "order", "properties": [{"path": "status", "label": "Status"},
                                                                             {"path": "colour", "label": "Colour"}]},
           "children": []}
    figure = {**FIGURE, "props": {**FIGURE["props"], "agg": "sum", "path": "no_such"}}
    said = pieces.not_resolved("c", _spec(f=bad, g=figure, h=CHART), graph=_graph())
    assert len(said) == 2
    assert 'filter column "f"' in said[0] and "colour" in said[0]
    assert 'figure "g"' in said[1] and "no_such" in said[1]


def test_a_model_may_not_add_one(monkeypatch):
    before = _spec(g=FIGURE)
    after = _spec(g=FIGURE, h=CHART)
    [said] = pieces.pieces_written(before, after, new=False)
    assert 'adds the chart "h"' in said


def test_each_piece_reads_its_entity():
    reads = pieces.depends(_spec(f=FILTERS, g=FIGURE, h=CHART), _graph())
    [(kind, target)] = reads
    assert kind == "entity" and sorted(reads[(kind, target)]) == ["f", "g", "h"]


def test_a_linked_category_saying_what_an_own_one_says_is_not_offered_twice():
    """Found on theLook (2026-10-11): an inventory item's filter column offered "Product category" twice — its own
    `product_category` and its product's `category`. The linked one is the same filter, and is not offered again."""
    from aughor.ontology.models import EntityProperty
    g = _graph()
    order = g.entities["Order"]
    # the order's own copy of its customer's name, first among its categories; the first linked one is the same
    order.properties = {"customer_name": EntityProperty(name="customer_name", display_name="Customer full name",
                                                        data_type="VARCHAR", semantic_type="dimension"), **order.properties}

    def run(query: dict):
        names = [m["name"] for m in query["measures"]]
        if query.get("by"):
            return [query["by"][0], "n"], [["A", 3], ["B", 2]], []
        if query.get("time"):
            return ["day", "n"], [], []
        return names, [[100 if n == "n" else 5 for n in names]], []
    filters = FO.propose(g, "order", run, today=TODAY)["filters"]
    labels = [f["label"] for f in filters]
    assert labels.count("Customer full name") == 1 and filters[0]["path"] == "customer_name", labels
    assert [f["via"] for f in filters if f["via"]] == ["Customer"] and "Customer full name" != filters[1]["label"], labels
