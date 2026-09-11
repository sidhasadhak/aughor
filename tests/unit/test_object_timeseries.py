"""ON-5 — timeseries properties: an object's latest value, and the history behind it.

ON-1b let a person bind an event table to an object type and say it was a `timeseries`; nothing read one. This
file holds what reading one now means, against a seeded warehouse and hand-written references: a timeseries
binding is reduced to each object's LATEST row, that reduction is one row per object (so it can neither multiply
nor invent objects), a reading with no time is never the latest, a tie on time still yields ONE row rather than
a mix of two, the value is built by instantiating a semiadditive `last` DECLARATION rather than hand-written
window SQL, and the object page shows the latest value, when it was measured, and the readings behind it.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.backing import apply_backing_measurements
from aughor.ontology.bindings import binding_problem
from aughor.ontology.models import OntologyGraph
from aughor.ontology.timeseries import (
    HISTORY_ROWS,
    history_sql,
    latest_columns,
    latest_declaration,
    latest_from,
)
from aughor.ontology.window_measures import compile_measure, from_declaration
from aughor.semantic.object_instances import get_object
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
from aughor.semantic.object_types import describe_object_type

from tests.unit.test_object_bindings import GRAPH, bind, ints, rows

#: Events over time (6,000 rows over 2,000 orders, and 20 more for one of them), plus a small table holding the two cases the reduction has to
#: decide: a reading with no time at all, and two readings at the very same time.
_EXTRA = """
CREATE TABLE ecommerce.order_events AS
SELECT printf('O%06d', 1 + i % 2000) AS order_id,
       TIMESTAMP '2023-01-01 00:00:00' + (i || ' hours')::INTERVAL AS event_at,
       CASE i % 3 WHEN 0 THEN 'packed' WHEN 1 THEN 'in_transit' ELSE 'delivered' END AS event,
       ROUND((10 + (i * 13.5) % 90)::NUMERIC, 2) AS backlog_hours
FROM range(1, 6001) t(i);
-- one order with a long history, so the page's cap is a real cap and not the whole of it
INSERT INTO ecommerce.order_events
SELECT 'O000001', TIMESTAMP '2022-01-01 00:00:00' + (i || ' days')::INTERVAL, 'packed', 5.00 FROM range(1, 21) t(i);
CREATE TABLE ecommerce.order_signals AS
SELECT * FROM (VALUES
  ('O000001', TIMESTAMP '2024-01-01 00:00:00', 10.0, 'a'),
  ('O000001', TIMESTAMP '2024-02-01 00:00:00', 20.0, 'b'),
  ('O000001', NULL,                            99.0, 'z'),
  ('O000002', TIMESTAMP '2024-03-01 00:00:00', 30.0, 'p'),
  ('O000002', TIMESTAMP '2024-03-01 00:00:00', 40.0, 'q'),
  ('O000003', NULL,                             7.0, 'n')
) AS t(order_id, seen_at, level, flag);
"""

#: The hand reference every compiled read is held to: each order's latest event row, found without a window
#: function at all — a correlated pick of the newest row, ties broken the way the declaration breaks them.
LATEST_REFERENCE = """
SELECT {select} FROM orders o
JOIN LATERAL (
  SELECT e.event, e.backlog_hours, e.event_at FROM order_events e
  WHERE e.order_id = o.order_id
  ORDER BY e.event_at DESC, e.event DESC, e.backlog_hours DESC LIMIT 1
) latest ON TRUE
WHERE {where}
"""

EVENTS = {"table": "order_events", "key": "order_id", "kind": "timeseries", "time_column": "event_at"}
SIGNALS = {"table": "order_signals", "key": "order_id", "kind": "timeseries", "time_column": "seen_at"}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("timeseries") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.execute(_EXTRA)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="timeseries-t")
    yield conn
    conn.close()


@pytest.fixture
def graph(db) -> OntologyGraph:
    g = OntologyGraph.model_validate_json(Path(GRAPH).read_text())
    apply_backing_measurements(g, db)
    return g


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def compile_(query: dict, graph: OntologyGraph):
    return compile_object_query(query, graph, fiscal_start_month=1)


def refusal(query: dict, graph: OntologyGraph) -> ObjectQueryRefused:
    with pytest.raises(ObjectQueryRefused) as exc:
        compile_(query, graph)
    return exc.value


# ── the reduction ───────────────────────────────────────────────────────────────────────────

def test_a_measured_timeseries_binding_is_read_now_and_says_how(db, graph):
    order = bind(graph, db, "Order", "events", EVENTS)
    [binding] = order.bindings
    assert binding.verified is True and binding_problem(order, binding) == ""
    said = describe_object_type(graph, "order")["summary"]
    assert "a timeseries binding, read as each object's latest value by event_at" in said


def test_a_timeseries_binding_with_no_time_column_has_no_latest_and_is_refused(db, graph):
    order = bind(graph, db, "Order", "events", EVENTS)
    binding = order.bindings[0]
    binding.time_column = ""                       # what an override that lost its time column would leave behind
    why = binding_problem(order, binding)
    assert "no time column" in why and "LATEST" in why
    assert latest_from(binding, "b1") == "" and history_sql(binding, "'O000001'") == ""
    assert "does not join" in refusal({"object_type": "order", "filters": [{"path": "event", "value": "packed"}],
                                       "measures": [{"agg": "count"}]}, graph).reason


def test_the_latest_value_is_a_declaration_instantiated_not_window_sql_written_here(db, graph):
    order = bind(graph, db, "Order", "events", EVENTS)
    [binding] = order.bindings
    assert latest_columns(binding) == ["event_at", "event", "backlog_hours"]
    declared = from_declaration(latest_declaration(binding, "event"))
    assert (declared.semiadditive, declared.range) == ("last", "current")
    assert declared.partition_by == ("tsrc.order_id",)
    # the ordering carries the time column AND every column the row supplies — see `test_a_tie_on_time…`
    assert declared.order_by == "tsrc.event_at, tsrc.event, tsrc.backlog_hours"
    compiled = compile_({"object_type": "order", "filters": [{"path": "event", "value": "packed"}],
                         "measures": [{"agg": "count"}]}, graph)
    assert compile_measure(declared) in compiled.sql       # the SQL IS the declaration's, not a second copy
    assert "LAST_VALUE" in compiled.sql and "UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING" in compiled.sql


def test_the_reduction_gives_one_row_per_object_so_a_to_many_source_cannot_multiply(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    counted = compile_({"object_type": "order", "filters": [{"path": "event", "op": "!=", "value": "nothing"}],
                        "measures": [{"agg": "count"}]}, graph)
    (orders,) = ints(db, "SELECT COUNT(*) FROM orders WHERE order_id IN (SELECT order_id FROM order_events)")
    assert rows(db, counted.sql) == [(float(orders),)]
    (events,) = ints(db, "SELECT COUNT(*) FROM order_events")
    assert events > orders * 2                          # the source really does hold many rows per object


def test_a_filter_on_a_latest_value_equals_its_reference(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    compiled = compile_({"object_type": "order", "filters": [{"path": "event", "value": "delivered"}],
                         "measures": [{"agg": "count"}]}, graph)
    assert rows(db, compiled.sql) == rows(db, LATEST_REFERENCE.format(where="latest.event = 'delivered'",
                                                                     select="COUNT(*)"))


def test_a_threshold_on_a_latest_value_equals_its_reference(db, graph):
    """The wave's receipt: the objects whose LATEST reading breaches a threshold."""
    bind(graph, db, "Order", "events", EVENTS)
    compiled = compile_({"object_type": "order", "filters": [{"path": "backlog_hours", "op": ">", "value": 80}],
                         "measures": [{"agg": "count"}, {"agg": "avg", "path": "backlog_hours", "decimals": 4}]},
                        graph)
    assert rows(db, compiled.sql) == rows(db, LATEST_REFERENCE.format(
        where="latest.backlog_hours > 80", select="COUNT(*), ROUND(AVG(latest.backlog_hours), 4)"))
    assert "> 80" in compiled.sql and "'80'" not in compiled.sql
    [noted] = compiled.bindings
    assert (noted["kind"], noted["treatment"], noted["time_column"]) == ("timeseries", "latest", "event_at")
    assert any("latest row by event_at" in line for line in compiled.plan)


def test_a_reading_with_no_time_is_never_the_latest(db, graph):
    bind(graph, db, "Order", "signals", SIGNALS)
    compiled = compile_({"object_type": "order", "filters": [{"path": "order_id", "op": "in",
                                                              "value": ["O000001", "O000003"]}],
                         "by": ["order_id"], "measures": [{"agg": "max", "path": "level"}]}, graph)
    # O000001's untimed 99.0 is not its latest (its latest is February's 20.0); O000003 has ONLY an untimed
    # reading, so it has no latest value at all — an empty cell, not the number that never said when. (The
    # warehouse wrapper hands a NULL back as the TEXT "NULL"; that is its own defect, filed, and what matters
    # here is that the cell is not 7.0.)
    assert rows(db, compiled.sql) == [("O000001", 20.0), ("O000003", "NULL")]


def test_a_tie_on_time_still_yields_one_row_rather_than_a_mix_of_two(db, graph):
    bind(graph, db, "Order", "signals", SIGNALS)
    compiled = compile_({"object_type": "order", "filters": [{"path": "order_id", "value": "O000002"}],
                         "by": ["flag"], "measures": [{"agg": "max", "path": "level"}]}, graph)
    # Two readings share the latest instant. Ordering on time alone would let `flag` come from one row and
    # `level` from the other; the declaration orders on every supplied column, so both come from the same one.
    assert rows(db, compiled.sql) == [("q", 40.0)]


# ── the object page ─────────────────────────────────────────────────────────────────────────

def test_the_object_page_shows_the_latest_value_when_it_was_measured_and_the_history_behind_it(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    page = get_object(graph, db, "order", "O000001")
    bound = {p["name"]: p for p in page.properties if p.get("binding")}
    assert set(bound) == {"event_at", "event", "backlog_hours"}
    latest = rows(db, "SELECT event_at, event, backlog_hours FROM order_events WHERE order_id = 'O000001' "
                      "ORDER BY event_at DESC, event DESC, backlog_hours DESC LIMIT 1")
    assert [(str(bound["event_at"]["value"]), bound["event"]["value"], float(bound["backlog_hours"]["value"]))] == [
        (str(latest[0][0]), latest[0][1], float(latest[0][2]))]
    at = bound["event"]["binding"]["at"]
    assert str(at) == str(bound["event_at"]["value"])          # the value, and WHEN it was measured, together
    assert bound["event"]["binding"]["kind"] == "timeseries"
    assert "latest row by event_at" in bound["event"]["binding"]["note"]

    [series] = page.timeseries
    assert (series["binding"], series["time_column"], series["limit"]) == ("events", "event_at", HISTORY_ROWS)
    assert str(series["latest_at"]) == str(bound["event_at"]["value"])
    (readings,) = ints(db, "SELECT COUNT(*) FROM order_events WHERE order_id = 'O000001'")
    assert len(series["rows"]) == min(readings, HISTORY_ROWS) and readings > HISTORY_ROWS
    when = [str(r[series["columns"].index("event_at")]) for r in series["rows"]]
    assert when == sorted(when, reverse=True)                  # newest first, which is how a person reads it
    assert when[0] == str(series["latest_at"])                 # and the first reading IS the latest value's


def test_an_object_no_reading_reaches_shows_the_property_empty_rather_than_someone_elses(db, graph):
    bind(graph, db, "Order", "signals", SIGNALS)
    page = get_object(graph, db, "order", "O000003")           # only an untimed reading
    bound = {p["name"]: p for p in page.properties if p.get("binding")}
    assert bound["level"]["value"] is None and bound["flag"]["value"] is None
    assert page.timeseries[0]["rows"] == []

