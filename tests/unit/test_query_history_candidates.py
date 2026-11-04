"""Arc NV-3 — the warehouse's own query history reaches the candidate door, and nothing else.

Three seams, each pinned: the history read (`aughor.db.query_history`) says when an engine keeps none and keeps the
engine's error as a value; the miner (`candidates.mine_from_query_log`) proposes only what recurs and what the join
map lacks, typed, with its frequency as evidence; and the door (`POST /ontology/candidates/mine`) refuses by name
while the organisation has not allowed the read, binds every candidate before offering it, and writes nothing.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.db.query_history import (
    HistoryRow, QueryHistory, not_platform_statement, read_query_history, rows_from_result, unsupported,
)
from aughor.ontology.candidates import (
    ORIGINS, QUERY_LOG_MIN_SUPPORT, Candidate, known_join_edges, mine, mine_from_query_log,
)


class _Result:
    def __init__(self, rows=(), error=""):
        self.rows, self.error = list(rows), error


# ── the read ──────────────────────────────────────────────────────────────────────────────

def test_an_engine_without_history_says_so():
    class Duck:
        dialect = "duckdb"
    h = read_query_history(Duck())
    assert not h.supported and h.rows == [] and "keeps no query history" in h.note
    assert unsupported("postgres").note.startswith("postgres")


def test_the_base_connection_answers_unsupported_by_default():
    from aughor.db.connection import DatabaseConnection
    assert "query_history" in DatabaseConnection.__dict__
    class Bare(DatabaseConnection):
        dialect = "duckdb"
        def execute(self, *a, **k): raise NotImplementedError
        def get_schema(self): return ""
        def test(self): return True, ""
        def close(self): pass
    h = Bare.query_history(Bare.__new__(Bare))
    assert isinstance(h, QueryHistory) and not h.supported


def test_rows_become_history_and_blanks_are_dropped():
    h = rows_from_result(_Result(rows=[["2026-11-03 10:00", "SELECT 1", "ana"], ["", "NULL", None], ["x", "  ", ""]]),
                         "snowflake", source="QUERY_HISTORY", hours=24, limit=10)
    assert h.supported and h.rows == [HistoryRow(ended_at="2026-11-03 10:00", sql="SELECT 1", user="ana")]
    assert h.statements == ["SELECT 1"] and h.note == ""
    assert h.to_dict()["count"] == 1


def test_an_empty_read_says_the_window_it_looked_in():
    h = rows_from_result(_Result(rows=[]), "clickhouse", source="system.query_log", hours=48, limit=10)
    assert h.supported and h.rows == [] and "last 48 hours" in h.note and "system.query_log" in h.note


def test_the_engines_error_is_a_value_never_a_raise():
    h = rows_from_result(_Result(error="permission denied on JOBS_BY_PROJECT"), "bigquery",
                         source="`region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT", hours=24, limit=10)
    assert h.supported and h.error.startswith("permission denied") and h.rows == []


def test_platform_and_catalog_statements_teach_nothing():
    assert not_platform_statement("SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id")
    assert not not_platform_statement("SELECT * FROM information_schema.columns")
    assert not not_platform_statement("SELECT query FROM system.query_log")
    assert not not_platform_statement("SELECT END_TIME FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())")


def test_the_four_engines_carry_a_reader_and_the_files_say_so():
    """A capability added to one connector class misses the others (ROADMAP §7, ×3) — every engine with a history
    overrides the base, by name."""
    import inspect
    from aughor.connectors.warehouse import bigquery, clickhouse, databricks, snowflake
    for mod, cls in ((snowflake, "SnowflakeConnection"), (clickhouse, "ClickHouseConnection"),
                     (bigquery, "BigQueryConnection"), (databricks, "DatabricksConnection")):
        klass = getattr(mod, cls)
        assert "query_history" in klass.__dict__, cls
        src = inspect.getsource(klass.__dict__["query_history"])
        assert "internal=True" in src and "rows_from_result" in src, cls
        # The door's contract (`db.dialects.sql_for_engine`): a statement written for the engine declares NOTHING;
        # declaring the engine's own dialect raised on the first live call (theLook, 2026-11-04).
        assert "sql_dialect=None" in src and "sql_dialect=self.dialect" not in src, cls


# ── the miner ─────────────────────────────────────────────────────────────────────────────

LOG = [
    "SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'shipped'",
    "SELECT * FROM customers cu JOIN orders ord ON cu.id = ord.customer_id WHERE ord.status = 'shipped'",
    "SELECT o.id, SUM(o.total) - SUM(o.refund) AS net_revenue FROM orders o JOIN regions r ON o.region_code = r.code GROUP BY 1",
    "SELECT SUM(o.total) - SUM(o.refund) AS net_revenue FROM orders o JOIN regions r ON o.region_code = r.code",
    "SELECT * FROM orders o JOIN sellers s ON o.seller_id = s.id",     # once: not how the warehouse is queried
]


def test_query_history_is_mined_into_typed_candidates_with_frequency_as_evidence():
    out = mine_from_query_log("c1", LOG, dialect="duckdb")
    kinds = {(c.kind, c.proposal) for c in out}
    assert ("join", "customers.id = orders.customer_id") in kinds
    assert ("join", "orders.region_code = regions.code") in kinds
    assert ("join", "orders.seller_id = sellers.id") not in kinds          # support 1 < QUERY_LOG_MIN_SUPPORT
    assert ("filter", "status IN ('shipped')") in kinds
    assert any(c.kind == "measure" and c.subject == "net_revenue" and "SUM(o.total) - SUM(o.refund)" in c.proposal
               for c in out)
    join = next(c for c in out if c.proposal == "customers.id = orders.customer_id")
    assert join.origin == "query_log" and join.source_rank == "mined" and join.subject == "customers"
    assert "2 of 5 statements" in join.evidence and "not in the join map" in join.evidence
    for c in out:
        c.validate()
    assert QUERY_LOG_MIN_SUPPORT == 2


def test_a_join_the_map_already_holds_is_not_proposed_again():
    known = known_join_edges({"joins": [{"t1": "orders", "c1": "customer_id", "t2": "customers", "c2": "id"}]})
    assert known == {"customers.id = orders.customer_id"}
    out = mine_from_query_log("c1", LOG, known_joins=known)
    assert not any(c.proposal == "customers.id = orders.customer_id" for c in out)
    assert any(c.proposal == "orders.region_code = regions.code" for c in out)


def test_nothing_in_nothing_out_and_unparseable_statements_are_skipped():
    assert mine_from_query_log("c1", []) == []
    assert mine_from_query_log("c1", ["", "   ", None]) == []
    assert mine_from_query_log("c1", ["this is not sql", "SELECT FROM WHERE"]) == []


def test_mine_takes_the_query_log_and_binds_each_candidate():
    seen = []
    def binder(c: Candidate):
        seen.append(c.kind)
        return (c.kind != "measure", "" if c.kind != "measure" else "alias")
    report = mine("c1", query_log=LOG, binder=binder)
    assert report.candidates and set(seen) == {"join", "filter", "measure"}
    assert all(c.kind != "measure" for c in report.offered)
    assert all(c.kind == "measure" and c.bind_error == "alias" for c in report.refused)
    assert "refused for not binding" in report.summary()


def test_every_origin_named_has_a_miner():
    assert set(ORIGINS) == {"verdict", "trusted_query", "query_log"}


# ── the door ──────────────────────────────────────────────────────────────────────────────

def test_the_door_refuses_by_name_while_the_organisation_has_not_allowed_the_read(monkeypatch):
    from aughor.orgsettings import allows as A
    from aughor.routers import ontology as R
    monkeypatch.setattr(A, "allows", lambda setting: False)
    with pytest.raises(HTTPException) as exc:
        R.mine_ontology_candidates(None, connection_id="c1", schema_name="main")
    assert exc.value.status_code == 409
    assert "off for this organisation" in exc.value.detail and A.WHERE in exc.value.detail
    assert "never rows" in exc.value.detail


def test_the_setting_is_an_organisations_choice_off_by_default():
    from aughor.orgsettings.allows import FORMER_ENV
    from aughor.orgsettings.models import OrgSettings
    assert "read_query_history" in FORMER_ENV and FORMER_ENV["read_query_history"] == ()
    assert OrgSettings().read_query_history is None


def test_the_door_mines_binds_and_writes_nothing(monkeypatch, tmp_path):
    """Allowed: the history is read through the connection, the graph's own edges are the known joins, every
    candidate is dry-run on the connection, and the report counts offered and refused."""
    from aughor.orgsettings import allows as A
    from aughor.routers import ontology as R
    from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph, OntologyRelationship

    monkeypatch.setattr(A, "allows", lambda setting: setting == "read_query_history")
    graph = OntologyGraph(
        connection_id="c1", schema_name="main", schema_fingerprint="fp",
        entities={
            "Order": OntologyEntity(id="Order", display_name="Order", source_tables=["orders"], identity_key="id",
                                    grain_verified=True, properties={"id": EntityProperty(name="id")}),
            "Customer": OntologyEntity(id="Customer", display_name="Customer", source_tables=["customers"],
                                       identity_key="id", grain_verified=True, properties={"id": EntityProperty(name="id")}),
            "Region": OntologyEntity(id="Region", display_name="Region", source_tables=["regions"], identity_key="code",
                                     grain_verified=True, properties={"code": EntityProperty(name="code")}),
        },
        relationships={"r": OntologyRelationship(
            id="r", from_entity="Order", to_entity="Customer", cardinality="N:1",
            join_sql="orders.customer_id = customers.id", from_table="orders", from_col="customer_id",
            to_table="customers", to_col="id", join_confidence="verified", value_overlap=0.9)},
    )
    monkeypatch.setattr(R, "_served_scope", lambda cid, s: "main")
    monkeypatch.setattr(R, "_get_ontology_graph", lambda cid, s=None: graph)

    dry_runs, closed = [], []
    class Conn:
        dialect = "duckdb"
        def query_history(self, *, hours, limit):
            rows = [HistoryRow(ended_at="t", sql=s) for s in LOG] + [HistoryRow(ended_at="t", sql="SELECT * FROM information_schema.tables")]
            return QueryHistory(engine="duckdb", supported=True, rows=rows, hours=hours, limit=limit, source="test")
        def dry_run(self, sql):
            dry_runs.append(sql)
            return ("regions" not in sql, "" if "regions" not in sql else "table regions has no column code")
        def close(self):
            closed.append(True)
    import aughor.db.connection as C
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda cid, s=None: Conn())

    out = R.mine_ontology_candidates(None, connection_id="c1", schema_name="main")
    assert out["history"]["supported"] and out["history"]["count"] == 6
    assert out["statements"] == 5                       # the catalog read taught nothing
    proposals = {c["proposal"] for c in out["offered"]} | {c["proposal"] for c in out["refused"]}
    assert "customers.id = orders.customer_id" not in proposals       # the graph already holds it
    assert "orders.region_code = regions.code" in proposals
    refused = {c["proposal"]: c["bind_error"] for c in out["refused"]}
    assert refused["orders.region_code = regions.code"] == "table regions has no column code"
    assert any(c["kind"] == "filter" and c["bound"] for c in out["offered"])
    measure = next(c for c in out["refused"] if c["kind"] == "measure")
    assert "alias" in measure["bind_error"]              # `o.total` names an alias: not bindable outside its statement
    assert any(sql.startswith("SELECT COUNT(*) FROM orders JOIN regions ON") for sql in dry_runs)
    assert out["mined"] == len(out["offered"]) + len(out["refused"]) and closed == [True]


def test_an_engine_without_history_is_said_through_the_door(monkeypatch):
    from aughor.orgsettings import allows as A
    from aughor.routers import ontology as R
    from aughor.ontology.models import OntologyGraph
    monkeypatch.setattr(A, "allows", lambda setting: True)
    monkeypatch.setattr(R, "_served_scope", lambda cid, s: "main")
    monkeypatch.setattr(R, "_get_ontology_graph",
                        lambda cid, s=None: OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp"))
    class Duck:
        dialect = "duckdb"
        def close(self): pass
    import aughor.db.connection as C
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda cid, s=None: Duck())
    out = R.mine_ontology_candidates(None, connection_id="c1")
    assert out["history"]["supported"] is False and out["offered"] == [] and out["mined"] == 0
    assert "keeps no query history" in out["summary"]
