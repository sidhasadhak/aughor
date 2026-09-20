"""Four metric routes answered for whichever definition matched the NAME first.

Measured live on 2026-09-20 against the running API:
``GET /metrics/revenue/value?conn_id=8233e4fd`` returned
``SELECT (SUM(total_amount)) AS _v FROM orders WHERE status <> 'cancelled'`` — the ``samples``
definition — together with the ``samples`` caveat prose, at HTTP 200, with no field naming whose
definition had run. theLook's own ``revenue`` is ``SUM(sale_price)`` over ``order_items``, and
``samples`` is not even in ``GET /connections`` any more: it is a dead connection id carrying two
orphaned metrics. It failed there only because ``total_amount`` does not exist on theLook. Where
the column names overlap it returns a confident number for a formula the caller is not looking at.

Root cause, one line in each route: ``get_metric(name)`` with no ``connection_id``. Read the
resolver (`semantic/metrics.py`) and the two behaviours are plain —

* ``connection_id=None`` → the second loop returns the FIRST row matching the name, whatever
  connection owns it;
* ``connection_id=X`` → a row scoped to X shadows, and only a GLOBAL row is used as a fallback.

So the fix is to pass the connection the caller already supplied, NOT to add a strict equality
check: a genuinely global definition must still answer for every connection, which is what
`test_a_global_definition_still_answers_for_any_connection` is here to stop anyone breaking.

The numbers do the work. ``SUM(a)`` is 10 and ``SUM(b)`` is 99 on the same row, so a test that
gets the wrong definition gets the wrong NUMBER — it cannot pass by comparing two strings that
were written next to each other.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.db.connection import DuckDBConnection
from aughor.semantic.metrics import GLOBAL_CONNECTION, MetricDefinition, save_metric

ALPHA, BETA, DEAD = "alpha", "beta", "a_connection_that_no_longer_exists"


@pytest.fixture(autouse=True)
def isolated_metrics(tmp_path, monkeypatch):
    """Own registry per test — `conftest`'s `AUGHOR_METRICS_PATH` is a session-scoped copy that
    every test file shares, so writes here would otherwise be visible to unrelated files."""
    path = tmp_path / "metrics.json"
    path.write_text("[]")
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def warehouse(tmp_path, monkeypatch):
    """One row where the two candidate formulas give different answers: SUM(a)=10, SUM(b)=99.

    A FRESH connection per call, not a shared one. These routes close the connection they were
    handed — correctly, since `open_connection_for` is what opened it — so a fixture that
    returns the same object twice has the second request running against a closed handle. That
    showed up as `value: null`, which is the route's HEALTHY-EMPTY answer, and for a while it
    looked like the fix had failed rather than the fixture.
    """
    path = tmp_path / "w.duckdb"
    w = duckdb.connect(str(path))
    try:
        w.execute("CREATE TABLE t AS SELECT 10 AS a, 99 AS b, TIMESTAMP '2026-01-01' AS ts")
    finally:
        w.close()
    opened: list = []

    def _open(_conn_id):
        db = DuckDBConnection(str(path))
        opened.append(db)
        return db

    monkeypatch.setattr("aughor.db.connection.open_connection_for", _open, raising=False)
    yield path
    for db in opened:
        try:
            db.close()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def two_definitions():
    """The same NAME on two connections, plus one orphaned on a connection that is gone."""
    save_metric(MetricDefinition(
        name="revenue", label="Alpha revenue", sql="SUM(a)", tables=["t"], connection=ALPHA,
        freshness_sla="alpha-sla", freshness_check_sql="SELECT MAX(ts) FROM t",
        quality_tests=[], owner="Alpha team", approved_by="Alpha", status="approved"))
    save_metric(MetricDefinition(
        name="revenue", label="Beta revenue", sql="SUM(b)", tables=["t"], connection=BETA,
        freshness_sla="beta-sla", freshness_check_sql="SELECT MAX(ts) FROM t",
        quality_tests=["SELECT COUNT(*) > 0 FROM t"], owner="Beta team", approved_by="Beta",
        status="approved"))
    save_metric(MetricDefinition(
        name="orphan", label="Orphan", sql="SUM(a)", tables=["t"], connection=DEAD,
        status="approved"))


# ── The defect, one route at a time ───────────────────────────────────────────

def test_value_runs_this_connections_formula(client):
    """The confirmed one. Alpha is saved FIRST, so a name-alone read returns Alpha for both."""
    assert client.get(f"/metrics/revenue/value?conn_id={ALPHA}").json()["value"] == 10
    beta = client.get(f"/metrics/revenue/value?conn_id={BETA}").json()
    assert beta["value"] == 99, "the value route ran another connection's formula"
    assert "SUM(b)" in beta["sql"]


def test_freshness_reads_this_connections_sla(client):
    assert client.get(f"/metrics/revenue/freshness?conn_id={ALPHA}").json()["sla"] == "alpha-sla"
    assert client.get(f"/metrics/revenue/freshness?conn_id={BETA}").json()["sla"] == "beta-sla"


def test_validate_runs_this_connections_quality_tests(client):
    """Alpha declares none and Beta declares one, so the wrong pick is visible in the result."""
    a = client.post(f"/metrics/revenue/validate?conn_id={ALPHA}").json()
    assert a["results"] == [] and "No quality tests" in a["message"]

    b = client.post(f"/metrics/revenue/validate?conn_id={BETA}").json()
    assert len(b["results"]) == 1, "validate ran another connection's quality tests"


def test_the_delete_trail_describes_the_metric_that_was_deleted(client):
    """`delete_metric` was already scoped; only the row read to DESCRIBE it was not, so the
    audit entry could name a different connection's owner than the definition that went. A
    trail that misdescribes what it recorded is worse than no trail — it is believed."""
    from aughor.kernel.ledger import Ledger

    r = client.delete(f"/metrics/revenue?connection={BETA}")
    assert r.status_code == 200, r.text

    events = Ledger.default().events(kind="metric.governance", limit=50)
    deletes = [e["payload"] for e in events
               if e.get("payload", {}).get("metric") == "revenue"
               and e["payload"].get("action") == "delete"]
    assert deletes, "no delete was journalled"
    assert deletes[0]["owner"] == "Beta team", \
        f"the trail credits {deletes[0]['owner']!r} for a delete scoped to {BETA}"


def test_a_metric_only_on_a_dead_connection_does_not_answer_for_another(client):
    """The `samples` shape exactly: two orphaned metrics on a connection id that is gone. Asking
    a LIVE connection for that name must be a 404, not a confident number from the orphan."""
    r = client.get(f"/metrics/orphan/value?conn_id={BETA}")
    assert r.status_code == 404, \
        f"answered for a definition owned by {DEAD!r}: {str(r.json())[:200]}"


def test_a_monitor_evaluates_its_own_connections_formula():
    """Found by sweeping for the defect CLASS rather than the three routes that were reported.

    `monitors/runner._resolve_sql` resolved `monitor.metric_name` by name alone while `Monitor`
    has always carried a required `conn_id` ("Connection this monitor runs against"). This one
    is worse than the read routes it shares the bug with: a monitor ALERTS on the number it
    computes, unattended, to people who never see which definition produced it.
    """
    from aughor.monitors.models import Monitor
    from aughor.monitors.runner import _resolve_sql

    beta = Monitor(conn_id=BETA, name="Beta revenue watch", metric_name="revenue")
    assert _resolve_sql(beta) == "SUM(b)", "the monitor resolved another connection's formula"

    alpha = Monitor(conn_id=ALPHA, name="Alpha revenue watch", metric_name="revenue")
    assert _resolve_sql(alpha) == "SUM(a)"


# ── The control: do not over-fix ──────────────────────────────────────────────

def test_a_global_definition_still_answers_for_any_connection(client):
    """A strict `metric.connection == conn_id` check would close the defect and break the
    feature: `"*"` means "applies everywhere", and the resolver's own fallback is the mechanism.
    This test fails if the fix is made with equality rather than by passing the connection."""
    save_metric(MetricDefinition(name="house_rule", label="House", sql="SUM(a)", tables=["t"],
                                 connection=GLOBAL_CONNECTION, status="approved"))
    r = client.get(f"/metrics/house_rule/value?conn_id={BETA}")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 10


def test_a_scoped_definition_shadows_the_global_one(client):
    """And the precedence that makes both of the above true at once."""
    save_metric(MetricDefinition(name="shadowed", label="Global", sql="SUM(a)", tables=["t"],
                                 connection=GLOBAL_CONNECTION, status="approved"))
    save_metric(MetricDefinition(name="shadowed", label="Beta", sql="SUM(b)", tables=["t"],
                                 connection=BETA, status="approved"))
    assert client.get(f"/metrics/shadowed/value?conn_id={ALPHA}").json()["value"] == 10
    assert client.get(f"/metrics/shadowed/value?conn_id={BETA}").json()["value"] == 99
