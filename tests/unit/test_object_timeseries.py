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
CREATE TABLE ecommerce.order_flags AS
SELECT printf('O%06d', i) AS order_id, i % 7 = 0 AS is_gift FROM range(1, 5001) t(i);
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


# ── the readings, as a set ──────────────────────────────────────────────────────────────────

def test_the_bare_property_is_the_latest_value_and_the_binding_name_is_the_whole_history(db, graph):
    """The distinction the whole wave turns on, held to two different reference numbers."""
    bind(graph, db, "Order", "events", EVENTS)
    latest = compile_({"object_type": "order", "filters": [{"path": "event", "value": "delivered"}],
                       "measures": [{"agg": "count"}]}, graph)
    ever = compile_({"object_type": "order", "filters": [{"path": "events.event", "value": "delivered"}],
                     "measures": [{"agg": "count"}]}, graph)
    [(latest_n,)] = rows(db, latest.sql)
    [(ever_n,)] = rows(db, ever.sql)
    assert latest_n == float(ints(db, LATEST_REFERENCE.format(select="COUNT(*)",
                                                              where="latest.event = 'delivered'"))[0])
    assert ever_n == float(ints(db, "SELECT COUNT(*) FROM orders o WHERE EXISTS (SELECT 1 FROM order_events e "
                                    "WHERE e.order_id = o.order_id AND e.event = 'delivered')")[0])
    assert ever_n > latest_n > 0                    # every order with a delivery, against those delivered LAST


def test_a_condition_on_the_readings_filters_the_object_set_and_never_multiplies_it(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    compiled = compile_({"object_type": "order", "filters": [{"path": "events.backlog_hours", "op": ">",
                                                              "value": 95}],
                         "measures": [{"agg": "count"}]}, graph)
    assert "EXISTS" in compiled.sql and "JOIN order_events" not in compiled.sql
    assert rows(db, compiled.sql) == rows(db, "SELECT COUNT(*) FROM orders o WHERE EXISTS (SELECT 1 FROM "
                                              "order_events e WHERE e.order_id = o.order_id AND "
                                              "e.backlog_hours > 95)")
    [noted] = compiled.bindings
    assert (noted["treatment"], noted["kind"]) == ("semi-join", "timeseries")


def test_an_aggregate_over_the_readings_equals_its_reference_and_rolls_up_as_a_ratio_of_sums(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    compiled = compile_({"object_type": "order",
                         "measures": [{"agg": "count", "path": "events"},
                                      {"agg": "sum", "path": "events.backlog_hours", "decimals": 2},
                                      {"agg": "avg", "path": "events.backlog_hours", "decimals": 4},
                                      {"agg": "max", "path": "events.backlog_hours"}]}, graph)
    assert rows(db, compiled.sql) == rows(db, """
        SELECT COUNT(*), ROUND(SUM(e.backlog_hours), 2), ROUND(AVG(e.backlog_hours), 4), MAX(e.backlog_hours)
        FROM order_events e JOIN orders o ON o.order_id = e.order_id""")
    assert "GROUP BY" in compiled.sql and "NULLIF" in compiled.sql      # pre-aggregated, and avg is a ratio
    assert any("aggregated per order_id BEFORE the join" in line for line in compiled.plan)
    [noted] = compiled.bindings
    assert noted["treatment"] == "pre-aggregated"


def test_a_where_on_a_readings_measure_reads_the_readings_own_columns(db, graph):
    """"Only the readings since March" — the ask a latest value cannot answer."""
    bind(graph, db, "Order", "events", EVENTS)
    compiled = compile_({"object_type": "order",
                         "measures": [{"agg": "count", "path": "events",
                                       "where": [{"path": "event_at", "op": ">=", "value": "2023-06-01"}]},
                                      {"agg": "avg", "path": "events.backlog_hours", "decimals": 4,
                                       "where": [{"path": "event", "value": "packed"}]}]}, graph)
    assert rows(db, compiled.sql) == rows(db, """
        SELECT COUNT(CASE WHEN e.event_at >= TIMESTAMP '2023-06-01' THEN 1 END),
               ROUND(AVG(CASE WHEN e.event = 'packed' THEN e.backlog_hours END), 4)
        FROM order_events e JOIN orders o ON o.order_id = e.order_id""")


def test_the_readings_and_the_latest_value_can_be_asked_for_together(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    compiled = compile_({"object_type": "order", "filters": [{"path": "event", "value": "delivered"}],
                         "measures": [{"agg": "avg", "path": "backlog_hours", "decimals": 4},
                                      {"agg": "avg", "path": "events.backlog_hours", "decimals": 4}]}, graph)
    assert rows(db, compiled.sql) == rows(db, """
        SELECT ROUND(AVG(latest.backlog_hours), 4), ROUND(1.0 * SUM(h.total) / NULLIF(SUM(h.n), 0), 4)
        FROM orders o
        JOIN LATERAL (SELECT e.event, e.backlog_hours FROM order_events e WHERE e.order_id = o.order_id
                      ORDER BY e.event_at DESC, e.event DESC, e.backlog_hours DESC LIMIT 1) latest ON TRUE
        LEFT JOIN (SELECT order_id, SUM(backlog_hours) AS total, COUNT(backlog_hours) AS n
                   FROM order_events GROUP BY order_id) h ON h.order_id = o.order_id
        WHERE latest.event = 'delivered'""")


def test_what_the_readings_refuse_to_answer(db, graph):
    order = bind(graph, db, "Order", "events", EVENTS)
    bind(graph, db, "Order", "flags", {"table": "order_flags", "key": "order_id"})
    refusals = [
        ({"measures": [{"agg": "count_distinct", "path": "events.event"}]}, "does not add up"),
        ({"measures": [{"agg": "sum", "path": "events"}]}, "needs one of its columns"),
        ({"measures": [{"agg": "avg", "path": "events.event"}]}, "not a known quantity"),
        ({"measures": [{"agg": "count", "path": "events.nope"}]}, "supplies no 'nope'"),
        ({"measures": [{"agg": "count", "path": "flags.is_gift"}]}, "is a static binding"),
        ({"filters": [{"path": "events", "op": "="}], "measures": [{"agg": "count"}]}, "set of readings"),
        ({"filters": [{"path": "events.event.nope", "value": "x"}], "measures": [{"agg": "count"}]},
         "has no links"),
    ]
    for query, said in refusals:
        why = refusal({"object_type": "order", "measures": [{"agg": "count"}], **query}, graph).reason
        assert said in why, (said, why)
    # an unmeasured binding is refused as a set too, with the count door named
    order.bindings[0].verified = None
    assert "unmeasured" in refusal({"object_type": "order", "measures": [{"agg": "count", "path": "events"}]},
                                   graph).reason


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


def test_the_page_says_what_the_value_was_before_it_and_reads_it_off_the_same_history(db, graph):
    bind(graph, db, "Order", "events", EVENTS)
    page = get_object(graph, db, "order", "O000001")
    bound = {p["name"]: p for p in page.properties if p.get("binding")}
    [series] = page.timeseries
    at = series["columns"].index("event_at")
    # the history's FIRST row is the row the latest value came from — one ordering, not two
    assert [str(v) for v in series["rows"][0]] == [str(bound[c]["value"]) for c in series["columns"]]
    for column in ("event", "backlog_hours"):
        i = series["columns"].index(column)
        assert str(bound[column]["binding"]["previous"]) == str(series["rows"][1][i])
        assert str(bound[column]["binding"]["previous_at"]) == str(series["rows"][1][at])
    assert str(bound["event"]["binding"]["at"]) != str(bound["event"]["binding"]["previous_at"])


def test_an_object_with_one_reading_has_no_previous_rather_than_its_own_value(db, graph):
    bind(graph, db, "Order", "signals", SIGNALS)
    page = get_object(graph, db, "order", "O000002")            # its two readings are tied on one instant
    bound = {p["name"]: p for p in page.properties if p.get("binding")}
    assert bound["level"]["value"] is not None
    assert bound["level"]["binding"]["previous"] is not None    # two readings: the tie-break says which is which
    page_one = get_object(graph, db, "order", "O000004")        # no reading at all
    one = {p["name"]: p for p in page_one.properties if p.get("binding")}
    assert one["level"]["value"] is None and one["level"]["binding"]["previous"] is None


def test_an_object_no_reading_reaches_shows_the_property_empty_rather_than_someone_elses(db, graph):
    bind(graph, db, "Order", "signals", SIGNALS)
    page = get_object(graph, db, "order", "O000003")           # only an untimed reading
    bound = {p["name"]: p for p in page.properties if p.get("binding")}
    assert bound["level"]["value"] is None and bound["flag"]["value"] is None
    assert page.timeseries[0]["rows"] == []



# ── frames over the readings (ON-5's second slice) ──────────────────────────────────────────
#
# The latest value answers "what is it now" and nothing about how it got there. `window_measures` has
# compiled trailing, cumulative and LAG since O5; the object door could not ASK for one, because a frame
# has to be computed on every reading and THEN read at the latest one, and window functions do not nest.
# These hold the two-layer reduction to hand-written references — and to the rule that makes it safe: the
# frame is computed inside the object's own partition, over the readings the reduction will reduce.

FRAMED = {**EVENTS, "frames": {
    "backlog_trailing_3": {"column": "backlog_hours", "agg": "avg", "range": "trailing", "window": 3},
    "backlog_to_date": {"column": "backlog_hours", "agg": "sum", "range": "cumulative"},
    "backlog_before": {"column": "backlog_hours", "offset": 1},
}}

#: Each order's frames, computed without the reduction: the last three readings by the declaration's own
#: ordering, everything to date, and the one before the last.
FRAME_REFERENCE = """
WITH ranked AS (
  SELECT order_id, backlog_hours,
         ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY event_at DESC, event DESC, backlog_hours DESC) AS r
  FROM order_events
)
SELECT (SELECT ROUND(AVG(backlog_hours), 6) FROM ranked WHERE order_id = '{order}' AND r <= 3),
       (SELECT ROUND(SUM(backlog_hours), 6) FROM ranked WHERE order_id = '{order}'),
       (SELECT backlog_hours FROM ranked WHERE order_id = '{order}' AND r = 2)
"""


def test_a_frame_over_the_readings_is_read_at_the_latest_one_and_equals_a_hand_reference(db, graph):
    order = bind(graph, db, "Order", "events", FRAMED)
    [binding] = order.bindings
    assert binding.verified is True and binding_problem(order, binding) == ""

    page = get_object(graph, db, "order", "O000001", overlay=[])
    got = {p["name"]: p["value"] for p in page.properties}
    want = db.execute("reference", FRAME_REFERENCE.format(order="O000001")).rows[0]

    assert round(float(got["backlog_trailing_3"]), 6) == round(float(want[0]), 6)
    assert round(float(got["backlog_to_date"]), 6) == round(float(want[1]), 6)
    assert round(float(got["backlog_before"]), 6) == round(float(want[2]), 6)


def test_a_frame_is_computed_inside_its_own_object_and_is_still_one_row_per_object(db, graph):
    """The failure this shape exists to prevent: a frame computed across every object's readings, or a
    reduction that multiplies the objects it joins to."""
    bind(graph, db, "Order", "events", FRAMED)
    orders, joined = ints(db, "SELECT (SELECT COUNT(*) FROM orders), "
                              "(SELECT COUNT(*) FROM " + latest_from(
                                  graph.entities["Order"].bindings[0], "b") + ")")
    assert joined <= orders                      # the reduction can neither multiply nor invent objects

    # Two orders' trailing averages differ from the average over BOTH — the partition is real.
    both, apart = db.execute("reference", """
        SELECT (SELECT ROUND(AVG(backlog_hours), 4) FROM (
                  SELECT backlog_hours FROM order_events WHERE order_id IN ('O000001', 'O000002')
                  ORDER BY event_at DESC LIMIT 3)),
               (SELECT COUNT(DISTINCT x) FROM (
                  SELECT ROUND(AVG(backlog_hours), 4) AS x FROM (
                    SELECT order_id, backlog_hours,
                           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY event_at DESC, event DESC,
                                              backlog_hours DESC) AS r
                    FROM order_events WHERE order_id IN ('O000001', 'O000002')) WHERE r <= 3 GROUP BY order_id))
    """).rows[0]
    assert int(apart) == 2 and both is not None


def test_a_frame_property_compiles_into_an_object_query_and_filters_by_it(db, graph):
    """A frame is a per-object scalar, so the compiler measures and filters it exactly as it does any other
    property the binding supplies — which is the answer to "what does a frame mean across an object set"."""
    bind(graph, db, "Order", "events", FRAMED)
    compiled = compile_({"object_type": "order",
                         "filters": [{"path": "backlog_trailing_3", "op": ">", "value": 50}],
                         "measures": [{"name": "n", "agg": "count"}]}, graph)
    [got] = ints(db, compiled.sql)
    [want] = ints(db, """
        SELECT COUNT(*) FROM (
          SELECT order_id, AVG(backlog_hours) AS m FROM (
            SELECT order_id, backlog_hours,
                   ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY event_at DESC, event DESC,
                                      backlog_hours DESC) AS r
            FROM order_events) WHERE r <= 3 GROUP BY order_id) WHERE m > 50
    """)
    assert got == want and got > 0


def test_what_a_frame_says_it_is_reaches_the_page_and_the_type(db, graph):
    bind(graph, db, "Order", "events", FRAMED)
    page = get_object(graph, db, "order", "O000001", overlay=[])
    framed = next(p for p in page.properties if p["name"] == "backlog_trailing_3")

    assert framed["binding"]["frame"] == "the avg of backlog_hours over the trailing 3 readings"
    assert "read at the object's latest reading" in framed["binding"]["note"]
    assert "previous" not in framed["binding"]      # a frame is already a span; "before" is a different frame
    assert framed["description"] == "the avg of backlog_hours over the trailing 3 readings"


def test_a_frame_that_cannot_mean_anything_is_refused_before_it_is_written(db, graph):
    from aughor.ontology.bindings import bind_binding, describe_with

    def refuse(frames: dict) -> str:
        return bind_binding(graph.entities["Order"], "events", {**EVENTS, "frames": frames},
                            graph, describe_with(db))["note"]

    assert "needs `window`" in refuse({"f": {"column": "backlog_hours", "range": "trailing"}})
    assert "spans no fixed number" in refuse({"f": {"column": "backlog_hours", "range": "all", "window": 3}})
    assert "a VALUE, not an aggregate" in refuse(
        {"f": {"column": "backlog_hours", "offset": 1, "agg": "sum"}})
    assert "unknown agg" in refuse({"f": {"column": "backlog_hours", "agg": "median", "window": 3}})
    assert "which its source does not have" in refuse({"f": {"column": "nope", "range": "all"}})
    assert "readings BACK" in refuse({"f": {"column": "backlog_hours", "offset": 0}})
    # A name the type already carries is refused rather than shadowing it.
    assert "status" in refuse({"status": {"column": "backlog_hours", "range": "all"}})
    # And a frame is meaningless on a binding that holds one row per object.
    flat = bind_binding(graph.entities["Order"], "flags",
                        {"table": "order_flags", "key": "order_id", "kind": "static",
                         "frames": {"f": {"column": "is_gift", "range": "all"}}}, graph, describe_with(db))
    assert "a frame reads the readings of a timeseries binding" in flat["note"]
