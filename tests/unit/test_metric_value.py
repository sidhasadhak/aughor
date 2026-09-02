"""DS-12 — the governed metric value, which had never been computed.

Measured live on 2026-09-01, before this module existed: `GET /metrics/revenue/value`
answered `{"value": null, "note": "Could not compute against 'fixture':
DuckDBConnection.execute() missing 1 required positional argument: 'sql'"}`. Both
metric-evaluation paths in `routers/metrics.py` called `db.execute(query)` against a
signature that has always been `execute(hypothesis_id, sql)`, and each swallowed the
TypeError into a field that reads as a data problem — `note` on the value route,
`status: "unknown"` on the health scorecard. The number the MCP tool's own docstring
promises is "the exact governed number, not an LLM re-derivation" was `None` every time.

The two copies also disagreed about what to compute: the value route applied the
metric's declared filters over its first table, the scorecard ran the bare aggregate
with no FROM and no filters. Two numbers for one governed definition is the failure the
metric registry exists to prevent, so what is pinned here is the SHARED builder — a
regression on either caller now fails one suite, not neither.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.db.connection import DuckDBConnection
from aughor.semantic.metrics import MetricDefinition, compute_value, value_query


@pytest.fixture
def orders(tmp_path):
    """Two cancelled rows among five, so a filter that is dropped shows up as a NUMBER."""
    path = tmp_path / "orders.duckdb"
    w = duckdb.connect(str(path))
    try:
        w.execute("""
            CREATE TABLE orders AS SELECT * FROM (VALUES
                (1, 100.0, 'shipped'), (2, 200.0, 'shipped'), (3, 300.0, 'delivered'),
                (4,  50.0, 'cancelled'), (5,  25.0, 'cancelled')
            ) AS t(id, total_amount, status)
        """)
    finally:
        w.close()
    db = DuckDBConnection(str(path))
    yield db
    db.close()


REVENUE = MetricDefinition(
    name="revenue", label="Revenue", sql="SUM(total_amount)",
    tables=["orders"], filters=["status <> 'cancelled'"], unit="$")


def test_a_governed_metric_computes_its_number(orders):
    """The whole point, and it has never held before this commit."""
    got = compute_value(REVENUE, orders)
    assert got.error == "", got.error
    assert got.value == 600.0


def test_the_declared_filters_are_part_of_the_definition(orders):
    """The scorecard's copy ran the bare aggregate. Had it ever executed, it would have
    scored revenue against 675 — cancelled orders included — while the value route
    reported 600 for the same metric on the same data. The filter is not a detail of
    one caller; it is what the metric MEANS."""
    unfiltered = REVENUE.model_copy(update={"filters": []})
    assert compute_value(unfiltered, orders).value == 675.0
    assert compute_value(REVENUE, orders).value == 600.0
    assert "status <> 'cancelled'" in value_query(REVENUE)


def test_a_metric_that_states_its_own_shape_is_run_verbatim(orders):
    """A full SELECT has already said what it is; wrapping it would change it."""
    full = MetricDefinition(name="big", label="Big",
                            sql="SELECT MAX(total_amount) FROM orders", tables=["orders"])
    assert value_query(full) == "SELECT MAX(total_amount) FROM orders"
    assert compute_value(full, orders).value == 300.0


def test_a_metric_the_schema_cannot_answer_reports_the_error_not_a_number(orders):
    """The live failure this wave found is the honest one: the two seeded metrics on
    this deployment name a schema no connection has. That must read as an error the
    reader can act on, never as a value and never as a raised exception inside a
    scheduled run."""
    wrong = MetricDefinition(name="nope", label="Nope", sql="SUM(nonexistent_column)",
                             tables=["orders"])
    got = compute_value(wrong, orders)
    assert got.value is None
    assert "nonexistent_column" in got.error


def test_no_rows_is_a_value_of_none_and_NOT_an_error(orders):
    """A metric whose filters match nothing has an answer: nothing. Reporting that as an
    error would send someone to check a connection that is working perfectly."""
    empty = REVENUE.model_copy(update={"filters": ["status = 'no-such-status'"]})
    got = compute_value(empty, orders)
    # SUM over zero rows is SQL NULL, which is "no value", not a failure.
    assert got.value is None and got.error == ""


def test_compute_value_never_raises_even_when_the_connector_cannot_run(orders):
    """It is called from a scheduled step. An exception here would fail a whole chain
    for a metric that simply cannot be asked on this connection."""
    class Broken:
        def execute(self, label, sql):
            raise RuntimeError("connector is down")
    got = compute_value(REVENUE, Broken())
    assert got.value is None and "connector is down" in got.error


def test_the_value_query_is_labelled_INTERNAL(orders):
    """`__metric_value__` is dunder-wrapped, which is what `_is_internal_query` reads.
    It is correct HERE — a single aggregate has nothing for the PII post-pass to redact
    — and is exactly the label a step that reads ROWS must not borrow."""
    seen = {}

    class Spy:
        def execute(self, label, sql):
            seen["label"] = label
            return orders.execute(label, sql)

    compute_value(REVENUE, Spy())
    from aughor.db.connection import _is_internal_query
    assert seen["label"] == "__metric_value__"
    assert _is_internal_query(seen["label"])
