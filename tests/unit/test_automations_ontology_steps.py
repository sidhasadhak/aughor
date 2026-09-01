"""DS-12 — the ontology plane as steps, and the list this plane could not publish.

Two kinds, and between them the wave's whole claim: a chain can act on the number the
semantic layer DEFINES rather than one an author typed, and it can run once per row of a
query someone vetted. Neither carries SQL — both name a governed object — which is the
difference between a component that references a capability and a step that IS one.

What is pinned:

* **The metric is read SCOPED to the automation's connection.** `list_metrics` shadows a
  global definition with a connection-scoped one of the same name, so an unscoped read
  computes the wrong "revenue" on a connection that deliberately redefined it — a
  silently-wrong number, which is the one failure a governed metric registry exists to
  prevent.
* **`rows` is a declared LIST and `count` is not.** §3.2 carried "nothing in this plane
  publishes a list" for three waves; the fix declares list-ness per KEY rather than
  reopening the published set, so the save-time refusal survives.
* **The row cap REFUSES.** W2's law one plane over: fanning over the first 50 of 4,000
  rows sends fifty messages and reads as though it sent all of them.
* **The query label is NOT the internal dunder form.** A metric reads one aggregate and
  may skip the PII post-pass; a query reads ROWS and must not.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.automations.engine import _dispatch_metric_value, _dispatch_trusted_query
from aughor.automations.models import Automation, Condition, Effect
from aughor.semantic import trusted_queries as tq
from aughor.semantic.metrics import MetricDefinition, list_metrics, save_metric

CONN = "ds12-conn"


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """A real DuckDB behind `open_connection_for`, so the steps run their true path."""
    path = tmp_path / "w.duckdb"
    w = duckdb.connect(str(path))
    try:
        w.execute("""
            CREATE TABLE orders AS SELECT * FROM (VALUES
                (1, 100.0, 'shipped'), (2, 200.0, 'shipped'),
                (3, 300.0, 'delivered'), (4, 50.0, 'cancelled')
            ) AS t(id, total_amount, status)
        """)
        w.execute("""
            CREATE TABLE accounts AS SELECT * FROM (VALUES
                ('a1', 'Acme', 0.9), ('a2', 'Globex', 0.8), ('a3', 'Initech', 0.7)
            ) AS t(id, name, churn_risk)
        """)
    finally:
        w.close()

    from aughor.db.connection import DuckDBConnection
    opened: list = []
    closed: list = []

    def _open(conn_id):
        if conn_id != CONN:
            raise KeyError(conn_id)
        db = DuckDBConnection(str(path))
        real_close = db.close

        def _counted_close():
            closed.append(db)
            return real_close()

        db.close = _counted_close       # type: ignore[method-assign]
        opened.append(db)
        return db

    import aughor.db.connection as dbmod
    monkeypatch.setattr(dbmod, "open_connection_for", _open)
    yield {"opened": opened, "closed": closed}


@pytest.fixture(autouse=True)
def _virgin_stores():
    """Both ontology stores are SESSION-scoped copies in the temp dir, so what this file
    saves is still there when the next file reads.

    The vetted-query file is a copy (conftest redirects `AUGHOR_TRUSTED_QUERIES_PATH`), so
    these saves cannot reach the tracked one — but they DO reach the next test. Found the
    expensive way: the metrics this suite defines leaked into the shared catalog and made
    `test_metric_dedup` fail in the full run while passing on its own. Every metric named
    here is prefixed `ds12_` and removed after, which is the same discipline VA-11's
    integration fixture already documents one plane over.
    """
    for q in tq.list_trusted():
        tq.delete_trusted(q.id)
    yield
    for q in tq.list_trusted():
        tq.delete_trusted(q.id)
    from aughor.semantic.metrics import delete_metric
    for m in list_metrics():
        if m.name.startswith("ds12_"):
            delete_metric(m.name)


def _automation(*effects) -> Automation:
    return Automation(name="ds12", conn_id=CONN,
                      conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                      effects=list(effects) or [Effect(kind="investigate",
                                                       config={"question": "q"})])


AUTO = _automation()


def _metric(name="ds12_revenue", connection="*", **kw) -> MetricDefinition:
    m = MetricDefinition(name=name, connection=connection, label=kw.pop("label", "Revenue"),
                         sql=kw.pop("sql", "SUM(total_amount)"), tables=["orders"],
                         filters=kw.pop("filters", ["status <> 'cancelled'"]),
                         unit="$", status="approved", **kw)
    save_metric(m)
    return m


def _query(qid="tq_accounts", sql="SELECT id, name FROM accounts ORDER BY id",
           question="which accounts are at risk?") -> tq.TrustedQuery:
    q = tq.TrustedQuery(id=qid, connection_id=CONN, question=question, sql=sql,
                        tables=["accounts"])
    tq.save_trusted(q)
    return q


# ── the governed metric ───────────────────────────────────────────────────────

def test_a_metric_step_publishes_the_governed_number(warehouse):
    _metric()
    out = _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "ds12_revenue"}), AUTO)
    assert out.status == "executed"
    assert out.data["value"] == 600.0        # 650 gross, less the cancelled 50
    assert out.data["unit"] == "$"
    assert "600" in out.message


def test_a_connection_scoped_definition_SHADOWS_the_global_one(warehouse):
    """The subtlety this wave nearly shipped wrong. Both definitions are named
    `ds12_revenue`; the connection-scoped one excludes nothing. An unscoped read returns
    600 — the global answer — on a connection whose own definition says 650."""
    _metric()                                                   # global, filters cancelled
    _metric(connection=CONN, filters=[])                        # this connection: gross
    scoped = [m for m in list_metrics(connection_id=CONN) if m.name == "ds12_revenue"]
    assert len(scoped) == 1 and scoped[0].filters == []
    out = _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "ds12_revenue"}), AUTO)
    assert out.data["value"] == 650.0, "the step read the global definition, not this one"


def test_an_unknown_metric_is_a_dispatch_error_not_a_failure(warehouse):
    out = _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "no_such_metric"}), AUTO)
    assert out.status == "dispatch_error" and "no_such_metric" in out.message


def test_a_metric_the_schema_cannot_answer_fails_with_the_engines_words(warehouse):
    """The live state of this deployment: two seeded metrics naming a schema no
    connection has. It must read as a failure with the reason attached, never as a
    value and never as an exception escaping into the run."""
    _metric(name="ds12_broken", sql="SUM(nope)", filters=[])
    out = _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "ds12_broken"}), AUTO)
    assert out.status == "failed" and "nope" in out.message


def test_a_metric_matching_no_rows_publishes_none_and_still_EXECUTES(warehouse):
    """A guard downstream asks `falsy` about it. Reporting "failed" would fire a
    fallback and page someone about a connection that answered correctly."""
    _metric(name="ds12_empty", filters=["status = 'nope'"])
    out = _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "ds12_empty"}), AUTO)
    assert out.status == "executed" and out.data["value"] is None
    assert "no value" in out.message


# ── the trusted query, and the list ───────────────────────────────────────────

def test_a_trusted_query_publishes_rows_columns_and_a_count(warehouse):
    _query()
    out = _dispatch_trusted_query(
        Effect(kind="trusted_query", config={"query_id": "tq_accounts"}), AUTO)
    assert out.status == "executed"
    assert out.data["count"] == 3
    assert out.data["columns"] == ["id", "name"]
    # Rows are DICTS, so a fanned step reads `item.name` — the shape `item_context`
    # already publishes for a dict item, so W2 needed nothing new.
    assert out.data["rows"][0] == {"id": "a1", "name": "Acme"}


def test_rows_is_the_declared_list_and_count_is_not():
    """Declared per KEY. Reopening the published set would have bought one list at the
    price of every unknown-key refusal on this kind."""
    from aughor.automations.dataflow import PUBLISHED_KEYS, publishes_list
    assert set(PUBLISHED_KEYS["trusted_query"]) == {"rows", "columns", "count"}
    assert publishes_list("trusted_query", "rows")
    assert not publishes_list("trusted_query", "count")


def test_a_query_on_another_connection_is_not_found(warehouse):
    """A trusted query is verified against the schema it was written for. Running one
    against a different connection is how a vetted query stops being vetted."""
    tq.save_trusted(tq.TrustedQuery(id="tq_elsewhere", connection_id="other",
                                    question="q", sql="SELECT 1", tables=[]))
    out = _dispatch_trusted_query(
        Effect(kind="trusted_query", config={"query_id": "tq_elsewhere"}), AUTO)
    assert out.status == "dispatch_error" and "tq_elsewhere" in out.message


def test_too_many_rows_is_REFUSED_not_truncated(warehouse):
    """W2's law one plane over. The cap is the fan-out cap on purpose: the reason to
    publish rows at all is to run once per one."""
    from aughor.automations.dataflow import MAX_FAN_OUT
    _query(qid="tq_many", sql=f"SELECT i FROM range(0, {MAX_FAN_OUT + 5}) t(i)")
    out = _dispatch_trusted_query(
        Effect(kind="trusted_query", config={"query_id": "tq_many"}), AUTO)
    assert out.status == "failed"
    assert "refused rather than truncated" in out.message
    assert str(MAX_FAN_OUT) in out.message


def test_exactly_the_cap_is_allowed(warehouse):
    """Off-by-one guard: the cap is a maximum, not a forbidden value. Asking for cap+1
    rows to detect overflow must not make cap rows look like overflow."""
    from aughor.automations.dataflow import MAX_FAN_OUT
    _query(qid="tq_exact", sql=f"SELECT i FROM range(0, {MAX_FAN_OUT}) t(i)")
    out = _dispatch_trusted_query(
        Effect(kind="trusted_query", config={"query_id": "tq_exact"}), AUTO)
    assert out.status == "executed" and out.data["count"] == MAX_FAN_OUT


def test_the_row_query_is_NOT_labelled_internal(warehouse):
    """The counterpart of the metric's label. `__…__` marks a query internal, which skips
    the PII/audit post-pass — correct for one aggregate, wrong for rows that may carry
    names and addresses into a chain that posts them somewhere."""
    from aughor.db.connection import _is_internal_query
    seen: dict = {}
    _query(qid="tq_label")

    import aughor.db.connection as dbmod
    real = dbmod.open_connection_for

    def _spy(conn_id):
        db = real(conn_id)
        inner = db.execute_bounded

        def _capture(label, sql, max_rows):
            seen["label"] = label
            return inner(label, sql, max_rows)

        db.execute_bounded = _capture       # type: ignore[method-assign]
        return db

    dbmod.open_connection_for = _spy        # type: ignore[assignment]
    try:
        _dispatch_trusted_query(
            Effect(kind="trusted_query", alias="rows", config={"query_id": "tq_label"}), AUTO)
    finally:
        dbmod.open_connection_for = real    # type: ignore[assignment]
    assert not _is_internal_query(seen["label"]), seen["label"]
    assert AUTO.id in seen["label"] and "rows" in seen["label"]


def test_the_connection_is_closed_on_every_path(warehouse):
    """These run on a schedule. A handle leaked per tick is a handle leaked per day.

    Counted, not inspected: the first version of this test asserted `... or True`, which
    is a test that passes for a leaking implementation exactly as readily as for a
    correct one — the vacuous shape this repo has a standing lesson about.
    """
    _query(qid="tq_close")
    _query(qid="tq_close_boom", sql="SELECT * FROM no_such_table")
    _metric(name="ds12_close")
    _metric(name="ds12_close_boom", sql="SUM(nope)", filters=[])

    _dispatch_trusted_query(
        Effect(kind="trusted_query", config={"query_id": "tq_close"}), AUTO)
    _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "ds12_close"}), AUTO)
    # …and the FAILING paths, which is where a close gets forgotten.
    _dispatch_trusted_query(
        Effect(kind="trusted_query", config={"query_id": "tq_close_boom"}), AUTO)
    _dispatch_metric_value(
        Effect(kind="metric_value", config={"metric": "ds12_close_boom"}), AUTO)

    assert len(warehouse["opened"]) == 4, warehouse["opened"]
    assert len(warehouse["closed"]) == 4, "a step left a warehouse handle open"
