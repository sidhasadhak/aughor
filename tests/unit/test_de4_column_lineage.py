"""DE-4 (ROADMAP §3.51; §6 item 37(f)) — column lineage over the statements the platform runs,
on the receipt.

What is asserted: which table columns an answer's columns come from and how surely (certain /
likely / possible); a row count resting on a table and no column, said rather than dropped;
the fallback to table level, with its reason, when columns cannot be traced; the receipt rows
and what a reader gets back from them; a column-level quality caveat riding only the answers
that read that column; the dependency walk reading the receipt's columns instead of text; and
the golden set's floor, measured on the engine the test runs on.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from aughor.db.schema_render import sqlglot_schema
from aughor.sql.lineage import ColumnRef, column_lineage, sqlglot_dialect
from aughor.trust.lineage_edges import column_edges, column_keys, columns_from_lineage, payload_columns

SCHEMA_TEXT = (
    "TABLE: ecommerce.orders  (5 rows)\n"
    "  order_id  BIGINT\n  customer_id  BIGINT\n  status  VARCHAR\n  total  DOUBLE\n"
    "TABLE: ecommerce.customers  (3 rows)\n"
    "  customer_id  BIGINT\n  country  VARCHAR\n"
)
SCHEMA = sqlglot_schema(SCHEMA_TEXT)

CTE_JOIN = (
    "WITH r AS (SELECT customer_id AS cid, SUM(total) AS spent FROM ecommerce.orders "
    "WHERE status = 'Complete' GROUP BY 1) "
    "SELECT c.country, r.spent, COUNT(*) AS n FROM r JOIN ecommerce.customers c "
    "ON c.customer_id = r.cid GROUP BY 1, 2"
)


def _rows(edges):
    return [{"relation": a, "ref": b, "detail": c} for a, b, c in edges]


# ── the tracer ─────────────────────────────────────────────────────────────────────

def test_schema_text_becomes_the_map_qualify_takes():
    assert SCHEMA == {"ecommerce": {
        "orders": {"order_id": "UNKNOWN", "customer_id": "UNKNOWN", "status": "UNKNOWN", "total": "UNKNOWN"},
        "customers": {"customer_id": "UNKNOWN", "country": "UNKNOWN"}}}
    # Bare tables: a flat map, which sqlglot matches to a statement's schema.table by its tail.
    assert sqlglot_schema("TABLE: t  (1 rows)\n  a  INT\n") == {"t": {"a": "UNKNOWN"}}
    assert sqlglot_schema("") == {}


def test_outputs_filters_joins_and_groups_each_with_how_it_was_resolved():
    lin = column_lineage(CTE_JOIN, dialect="duckdb", schema=SCHEMA)
    assert lin.level == "column" and lin.note is None
    by = {o.name: o for o in lin.outputs}
    # Read directly from a table the outer select names: certain.
    assert by["country"].sources == (ColumnRef("ecommerce.customers", "country"),)
    assert by["country"].confidence == "certain"
    # Read through the CTE: the parser bound it, but a derived table stands between — likely.
    assert by["spent"].sources == (ColumnRef("ecommerce.orders", "total"),)
    assert by["spent"].confidence == "likely"
    # Filter inside the CTE, join on both sides, groups through the CTE's alias.
    assert (ColumnRef("ecommerce.orders", "status"), "certain") in lin.filters
    assert {r for r, _ in lin.joins} == {ColumnRef("ecommerce.customers", "customer_id"),
                                         ColumnRef("ecommerce.orders", "customer_id")}
    assert dict(lin.joins)[ColumnRef("ecommerce.orders", "customer_id")] == "likely"
    # The outer GROUP BY through the CTE's alias, and the CTE's own GROUP BY customer_id.
    assert {r for r, _ in lin.groups} == {ColumnRef("ecommerce.customers", "country"),
                                          ColumnRef("ecommerce.orders", "total"),
                                          ColumnRef("ecommerce.orders", "customer_id")}


def test_a_row_count_rests_on_its_tables_and_no_column_and_is_said_so():
    lin = column_lineage("SELECT COUNT(*) AS n FROM ecommerce.orders", dialect="duckdb")
    (n,) = lin.outputs
    assert n.sources == () and n.tables == ("ecommerce.orders",) and n.confidence == "certain"
    edge = [e for e in lin.edges() if e["role"] == "output"][0]
    assert edge["table"] == "ecommerce.orders" and edge["column"] is None
    assert "no column" in edge["note"]
    # Over a CTE join, the count rests on every table the join reads — the CTE's included,
    # less surely.
    lin = column_lineage(CTE_JOIN, dialect="duckdb", schema=SCHEMA)
    n = {o.name: o for o in lin.outputs}["n"]
    assert set(n.tables) == {"ecommerce.customers", "ecommerce.orders"} and n.confidence == "likely"


def test_without_a_schema_a_single_source_binds_by_name_only_and_an_alias_binds_surely():
    lin = column_lineage("SELECT status FROM orders WHERE total > 5", dialect="duckdb")
    assert lin.outputs[0].sources == (ColumnRef("orders", "status"),)
    assert lin.outputs[0].confidence == "possible"
    assert lin.note == "no schema: columns attributed by name"
    lin = column_lineage("SELECT o.status FROM orders o", dialect="duckdb")
    assert lin.outputs[0].confidence == "certain", "the author qualified it: no schema needed"


def test_select_star_without_a_schema_falls_back_to_tables_and_says_why():
    lin = column_lineage("SELECT * FROM a JOIN b ON a.id = b.id", dialect="duckdb")
    assert lin.level == "table" and lin.tables == ["a", "b"] and lin.outputs == []
    assert "SELECT *" in (lin.note or "")


def test_select_star_with_a_schema_expands_to_every_column():
    lin = column_lineage("SELECT * FROM ecommerce.customers", dialect="duckdb", schema=SCHEMA)
    assert [(o.name, o.confidence, o.sources[0].column) for o in lin.outputs] == [
        ("customer_id", "certain", "customer_id"), ("country", "certain", "country")]


def test_not_a_select_and_not_parsed_are_table_level_with_the_reason():
    lin = column_lineage("INSERT INTO t VALUES (1)", dialect="duckdb")
    assert lin.level == "table" and "not a SELECT" in lin.note
    lin = column_lineage("SELEC x FROM", dialect="duckdb")
    assert lin.level == "table" and "not parsed" in lin.note


def test_dialect_names_the_door_records_are_understood_and_an_unknown_one_parses_generically():
    assert sqlglot_dialect("postgresql") == "postgres"
    assert sqlglot_dialect("exasol") == "exasol"
    assert sqlglot_dialect("madeup") is None
    lin = column_lineage("SELECT a FROM t", dialect="madeup")
    assert lin.outputs[0].sources == (ColumnRef("t", "a"),)


def test_bigquery_spelling_keeps_the_project_and_dataset():
    lin = column_lineage("SELECT status, COUNT(*) n FROM `proj.ds.orders` GROUP BY 1", dialect="bigquery")
    assert lin.outputs[0].sources == (ColumnRef("proj.ds.orders", "status"),)
    assert lin.outputs[1].tables == ("proj.ds.orders",)


# ── the receipt rows ───────────────────────────────────────────────────────────────

def test_receipt_rows_one_per_column_plus_one_saying_columns_were_traced():
    rows = column_edges([CTE_JOIN], dialect="duckdb", schema_text=SCHEMA_TEXT)
    assert rows[-1] == ("lineage", "level:column", None)
    cols = {ref: json.loads(detail) for rel, ref, detail in rows if rel == "column"}
    assert cols["column:ecommerce.orders.total"] == {"roles": ["group", "output"], "confidence": "likely", "as": ["spent"]}
    assert cols["column:ecommerce.orders.status"] == {"roles": ["filter"], "confidence": "certain"}
    assert cols["column:ecommerce.customers.customer_id"] == {"roles": ["join"], "confidence": "certain"}
    assert cols["table:ecommerce.orders"]["as"] == ["n"] and "no column" in cols["table:ecommerce.orders"]["note"]
    assert payload_columns(rows) == [
        "ecommerce.customers.country", "ecommerce.customers.customer_id",
        "ecommerce.orders.customer_id", "ecommerce.orders.status", "ecommerce.orders.total"]


def test_a_reader_gets_the_columns_back_and_an_untraced_receipt_reads_as_not_traced():
    rows = column_edges([CTE_JOIN], dialect="duckdb", schema_text=SCHEMA_TEXT)
    info = columns_from_lineage(_rows(rows))
    assert info["level"] == "column" and info["note"] is None
    assert {c["column"] for c in info["columns"]} == {"country", "customer_id", "status", "total"}
    assert {t["table"] for t in info["tables_only"]} == {"ecommerce.customers", "ecommerce.orders"}
    assert column_keys(_rows(rows)) == ["customers.country", "customers.customer_id",
                                        "orders.customer_id", "orders.status", "orders.total"]
    # A receipt from before DE-4 carries tables and no column rows: not traced, not "none".
    old = [{"relation": "input", "ref": "table:orders", "detail": None}]
    assert columns_from_lineage(old)["level"] is None
    assert column_keys(old) is None


def test_table_level_fallback_rides_the_receipt_with_its_reason():
    rows = column_edges(["SELECT * FROM a JOIN b ON a.id = b.id"], dialect="duckdb")
    assert [r for r in rows if r[0] == "column"] == []
    assert rows[-1][0:2] == ("lineage", "level:table") and "SELECT *" in rows[-1][2]
    assert column_keys(_rows(rows)) is None


def test_the_strongest_resolution_wins_when_statements_disagree():
    rows = column_edges(["SELECT r.total FROM (SELECT total FROM ecommerce.orders) r",
                         "SELECT o.total FROM ecommerce.orders o"],
                        dialect="duckdb", schema_text=SCHEMA_TEXT)
    detail = json.loads(dict((ref, d) for _rel, ref, d in rows if ref.startswith("column:"))["column:ecommerce.orders.total"])
    assert detail["confidence"] == "certain"


def test_no_statements_means_no_rows():
    assert column_edges([], dialect="duckdb") == []


# ── caveats per column ─────────────────────────────────────────────────────────────

def test_a_column_caveat_rides_only_the_answers_that_read_the_column():
    from aughor.quality.caveats import caveats_for_answer
    from aughor.quality.results import Result, record

    record(Result(connection_id="de4", table_name="orders", column_name="status", rule_name="status_enum",
                  passed=False, detail="holds values outside the enumerated set"), org_id="default")
    record(Result(connection_id="de4", table_name="orders", rule_name="fresh",
                  passed=False, detail="last row is 3 days old"), org_id="default")

    read_total = caveats_for_answer("de4", ["orders"], org_id="default", columns=["ecommerce.orders.total"])
    assert len(read_total) == 1 and "3 days old" in read_total[0]
    assert not any("status" in c for c in read_total), "the answer never read orders.status"

    read_status = caveats_for_answer("de4", ["orders"], org_id="default", columns=["orders.status"])
    assert len(read_status) == 2 and any(c.startswith("`orders.status`") for c in read_status)

    # Columns not traced: every caveat for the table applies, as before DE-4.
    assert len(caveats_for_answer("de4", ["orders"], org_id="default")) == 2


def test_the_builder_receipt_carries_its_columns_and_the_public_receipt_shows_them():
    from aughor.kernel.ledger import Ledger
    from aughor.routers.query import _write_builder_receipt
    from aughor.trust.receipt import build_public_receipt

    rid = _write_builder_receipt("de4-conn", "SELECT o.status, COUNT(*) AS n FROM ecommerce.orders o GROUP BY 1")
    assert rid
    raw = Ledger.default().receipt_by_id(rid)
    rels = {(e["relation"], e["ref"]) for e in raw["lineage"]}
    assert ("input", "table:orders") in rels or ("input", "table:ecommerce.orders") in rels
    assert ("column", "column:ecommerce.orders.status") in rels
    assert ("lineage", "level:column") in rels
    assert raw["artifact"]["payload"]["columns"] == ["ecommerce.orders.status"]
    public = build_public_receipt(raw, signed=False)
    assert public["columns"]["level"] == "column"
    assert public["columns"]["columns"][0]["column"] == "status"
    assert public["columns"]["columns"][0]["confidence"] == "certain"


# ── the dependency walk reads the receipt, not the text ────────────────────────────

def _n(nid, kind, label="", **data):
    return SimpleNamespace(id=nid, kind=kind, label=label or nid, data=data)


def _e(from_id, to_id, kind="grounded_in"):
    return SimpleNamespace(id=f"{from_id}->{to_id}", from_id=from_id, to_id=to_id, kind=kind)


def _graph():
    nodes = [
        _n("table:orders", "table", source_tables=["ecommerce.orders"]),
        _n("finding:status", "finding", "status mix", sql="SELECT status FROM ecommerce.orders",
           columns=["ecommerce.orders.status"]),
        _n("finding:total", "finding", "revenue", sql="SELECT SUM(total) FROM ecommerce.orders",
           columns=["ecommerce.orders.total"]),
        _n("finding:old", "finding", "an older finding", sql="SELECT count(*) FROM ecommerce.orders"),
        _n("brief:b", "brief", "the brief"),
    ]
    edges = [_e("finding:status", "table:orders"), _e("finding:total", "table:orders"),
             _e("finding:old", "table:orders"), _e("brief:b", "finding:total", "derived_from")]
    return SimpleNamespace(nodes={n.id: n for n in nodes}, edges=edges)


def test_dependents_of_a_column_keep_what_read_it_and_what_was_never_traced():
    from aughor.govern.lineage import dependents_of

    r = dependents_of(_graph(), "table:orders", column="status")
    by = {d.node_id: d for d in r.dependents}
    assert set(by) == {"finding:status", "finding:old"}, "finding:total read another column, and its brief with it"
    assert by["finding:status"].site == "reads orders.status" and by["finding:status"].site_kind == "column"
    assert "columns not traced" in by["finding:old"].site


def test_without_a_column_every_dependent_is_reported_and_a_traced_site_names_its_columns():
    from aughor.govern.lineage import dependents_of

    r = dependents_of(_graph(), "table:orders")
    by = {d.node_id: d for d in r.dependents}
    assert set(by) == {"finding:status", "finding:total", "finding:old", "brief:b"}
    assert by["finding:total"].site == "reads orders.total"
    assert by["finding:old"].site_kind == "sql", "no columns on the node: the text scan, as before"


def test_a_finding_node_carries_the_receipts_columns_only_when_it_has_them():
    from aughor.ontology.context_graph import finding_node_data

    assert "columns" not in finding_node_data({"id": "f", "sql": "x", "tables": ["t"]})
    assert finding_node_data({"id": "f", "sql": "x", "tables": ["t"], "columns": ["t.a"]})["columns"] == ["t.a"]


# ── the golden set, measured where the test runs ──────────────────────────────────

def test_golden_set_floor_every_output_resolves_or_rests_on_a_table():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.de4_lineage_precheck import golden_statements, seeded_schema

    schema = seeded_schema()
    statements = golden_statements()
    assert len(statements) == 66
    outputs = resolved = 0
    unresolved_exprs: list[str] = []
    for _sid, sql in statements:
        lin = column_lineage(sql, dialect="duckdb", schema=schema)
        assert lin.level == "column", (_sid, lin.note)
        for o in lin.outputs:
            outputs += 1
            if o.sources:
                resolved += 1
            else:
                assert o.tables, (_sid, o.name, "an output with no column must rest on a table")
                unresolved_exprs.append(o.expression)
    assert outputs == 136
    assert resolved >= 122, f"{resolved} of {outputs} — the floor the pre-check measured"
    assert all("COUNT(*)" in e.upper() for e in unresolved_exprs), unresolved_exprs
