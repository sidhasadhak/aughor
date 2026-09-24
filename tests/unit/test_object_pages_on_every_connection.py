"""PENDING item 25 — object pages right on every connection.

Measured 2026-09-24 by reading, each fixed at its cause:

* findings cited an object only by a STRING literal parsed as generic SQL — so on theLook (BigQuery: backticked
  `project.dataset.table`, integer ids) no finding ever cited one object, and a finding about another user showed
  as "users in general";
* one finding that could not be read ended the scan, dropping every finding after it, in silence;
* a metric reaching another connection compiles to a PLAN whose SQL is for a reader — and the page ran it;
* SQL NULL reached the page as the word "NULL";
* the query over an organisation's ontology merged no accepted edit, and its Withdraw sent the ontology's token as
  the connection, so every withdrawal answered "no such edit";
* LuxExperience's metrics panel was empty: the shipped revenue reads `total_amount`, which its orders lack.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.models import OntologyGraph
from aughor.semantic import object_context as OC
from aughor.semantic.object_instances import ObjectInstance

REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.artifacts_of_kind", lambda self, *a, **k: [])
    return OntologyGraph.model_validate(json.loads(SAMPLES.read_text()))


def _order(pk: str) -> ObjectInstance:
    return ObjectInstance(object_type="order", type_id="Order", type_name="Order", key="order_id", pk=pk,
                          title=None, properties=[], links=[])


def _findings(monkeypatch, graph, instance, findings):
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: findings)
    return OC._object_findings("conn-25", "ecommerce", graph, graph.entities["Order"], instance)


# ── citations on every warehouse ──────────────────────────────────────────────────────────

def test_a_bigquery_finding_with_an_integer_key_cites_its_object(graph, monkeypatch):
    rows, unread = _findings(monkeypatch, graph, _order("12345"), [
        {"id": "this", "finding": "three lines",
         "sql": "SELECT COUNT(*) FROM `bigquery-public-data.ecommerce.order_items` AS i WHERE i.order_id = 12345"},
        {"id": "other", "finding": "another order",
         "sql": "SELECT * FROM `bigquery-public-data.ecommerce.orders` WHERE order_id = 999"},
        {"id": "all", "finding": "orders by status",
         "sql": "SELECT status, COUNT(*) FROM `bigquery-public-data.ecommerce.orders` GROUP BY 1"},
    ])
    assert unread == 0
    assert [(r["id"], r.get("scope")) for r in rows] == [("this", None), ("all", "type")]
    assert rows[0]["matched"] == "order_items.order_id = '12345'"


def test_the_guards_still_read_only_text_literals(graph):
    """The extractor is shared with the join guard, which binds TEXT values: numbers are an opt-in."""
    from aughor.sql.join_guard import extract_filter_literals
    sql = "SELECT * FROM orders WHERE order_id = 12345 AND status = 'shipped'"
    assert extract_filter_literals(sql) == [("orders", "status", "shipped", "=")]
    assert ("orders", "order_id", "12345", "=") in extract_filter_literals(sql, numbers=True)


def test_one_unreadable_finding_is_counted_and_the_rest_are_listed(graph, monkeypatch):
    real = OC.about_segment

    def about(finding, segment, tables):
        if finding.get("id") == "bad":
            raise ValueError("a finding the store half-wrote")
        return real(finding, segment, tables)
    monkeypatch.setattr(OC, "about_segment", about)
    rows, unread = _findings(monkeypatch, graph, _order("O000123"), [
        {"id": "bad", "finding": "?", "sql": "SELECT status FROM orders GROUP BY 1"},
        {"id": "after", "finding": "orders by month", "sql": "SELECT month, COUNT(*) FROM orders GROUP BY 1"},
    ])
    assert unread == 1 and [r["id"] for r in rows] == ["after"]


# ── metrics ───────────────────────────────────────────────────────────────────────────────

class _Db:
    dialect = "duckdb"

    def __init__(self, cell="42"):
        self.ran: list[str] = []
        self.cell = cell

    def execute(self, label, sql):
        self.ran.append(sql)
        return SimpleNamespace(error=None, rows=[[self.cell]])


def _customer() -> ObjectInstance:
    return ObjectInstance(object_type="customer", type_id="Customer", type_name="Customer", key="customer_id",
                          pk="C00042", title=None, properties=[{"name": "customer_id", "value": "C00042"}], links=[])


def test_a_metric_that_reads_another_connection_never_runs_its_display_sql(graph, monkeypatch):
    from aughor.semantic.object_query import compile_object_query

    def planned(query, graph, **kw):
        compiled = compile_object_query(query, graph, **kw)
        compiled.cross_source = object()        # as ON-8 compiles a read by key from another connection
        return compiled
    monkeypatch.setattr(OC, "compile_object_query", planned)
    db = _Db()
    rows = OC.object_metrics(graph, db, graph.entities["Customer"], _customer())
    assert rows and db.ran == [], "display-only SQL was run on the home connection"
    assert all("reads another connection" in r["refused"] for r in rows)

    ran_as_plan: list = []
    rows = OC.object_metrics(graph, db, graph.entities["Customer"], _customer(),
                             run_cross_source=lambda c: ran_as_plan.append(c) or SimpleNamespace(error=None, rows=[["7"]]))
    assert db.ran == [] and len(ran_as_plan) == len(rows) and {r["value"] for r in rows} == {"7"}


def test_a_metric_with_nothing_to_measure_is_no_value_not_the_word(graph):
    rows = OC.object_metrics(graph, _Db(cell="NULL"), graph.entities["Customer"], _customer())
    assert rows and all(r["value"] is None for r in rows if "refused" not in r)


def test_every_metric_measures_this_object_whatever_the_one_before_measured(graph):
    """A measured value once shadowed the scope's key: the second metric filtered `customer_id = '42'`."""
    db = _Db(cell="42")
    OC.object_metrics(graph, db, graph.entities["Customer"], _customer())
    assert len(db.ran) >= 2 and all("'C00042'" in sql for sql in db.ran), db.ran


# ── an organisation's ontology ────────────────────────────────────────────────────────────

def test_a_domain_read_merges_each_types_own_edits_from_where_its_rows_live(monkeypatch):
    from aughor.routers import objects as R
    customer = SimpleNamespace(api_name="customer", id="Customer")
    order = SimpleNamespace(api_name="order", id="Order")
    domain = SimpleNamespace(entities={"Customer": customer, "Order": order})
    lives = {"Customer": "crm", "Order": "shop"}
    monkeypatch.setattr("aughor.ontology.sources.entity_source", lambda g, e: lives[e.id])
    edits = {"crm": [SimpleNamespace(object_type="customer", id="e1"), SimpleNamespace(object_type="order", id="e2")],
             "shop": [SimpleNamespace(object_type="order", id="e3"), SimpleNamespace(object_type="customer", id="e4")]}
    monkeypatch.setattr(R, "_accepted_edits", lambda conn: edits[conn])
    assert sorted(e.id for e in R._domain_edits(domain)) == ["e1", "e3"]      # never another connection's same-named type


def test_withdrawing_on_an_organisations_ontology_says_where_to_withdraw():
    from fastapi.testclient import TestClient

    from aughor.api import app
    # by its handler's name: the route's frozen path spells a retired word (tests/unit/test_vocabulary_ratchet.py)
    res = TestClient(app).delete(app.url_path_for("withdraw_annotation", edit_id="e1"),
                                 params={"connection_id": "domain:acme"})
    assert res.status_code == 400 and "connection its object lives on" in res.json()["detail"]


# ── LuxExperience's metrics ───────────────────────────────────────────────────────────────

def test_luxexperience_ships_gmv_and_gmv_per_order_that_compile_for_one_order(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", REPO / "data" / "shipped" / "ontology_overrides")
    import aughor.db.registry as registry
    monkeypatch.setattr(registry, "scope_key_of", lambda conn: "luxexperience" if conn == "c0ffee42" else "")
    snapshot = json.loads((REPO / "evals" / "ablation_luxexperience_business_ontology.json").read_text())
    before = OntologyGraph.model_validate(snapshot)
    order = before.entities["Order"]
    from aughor.semantic.object_query import compile_object_query, metric_on
    assert not [m for m in before.metrics.values() if m.verified and metric_on(m, order)], "the panel was not empty"

    graph, _ = OV.apply_overrides(before, "c0ffee42", "luxexperience")
    shown = {mid: m for mid, m in graph.metrics.items() if m.verified and metric_on(m, graph.entities["Order"])}
    assert {mid: m.display_name for mid, m in shown.items()} == {"gmv": "GMV", "gmv_per_order": "GMV per order"}
    for mid in shown:
        sql = compile_object_query({"object_type": "order", "filters": [{"path": "order_id", "value": "LX-1"}],
                                    "measures": [{"name": "value", "metric": mid}]}, graph).sql
        assert "gmv_eur" in sql and "LX-1" in sql, sql


def test_the_shipped_binding_is_the_real_binder_against_the_recorded_schema():
    """What the shipped `bound: true` rests on — and that the same check refuses what LuxExperience lacks."""
    import duckdb

    from aughor.ontology.overrides import OntologyOverride, bind_overrides
    snapshot = json.loads((REPO / "evals" / "ablation_luxexperience_business_ontology.json").read_text())
    graph = OntologyGraph.model_validate(snapshot)
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA luxexperience")
    con.execute("CREATE TABLE luxexperience.orders (" + ", ".join(
        f'"{n}" {p.data_type}' for n, p in graph.entities["Order"].properties.items()) + ")")

    def explain(sql):
        try:
            con.execute(f"EXPLAIN {sql}")
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None
    for formula, bound in (("SUM(gmv_eur)", True), ("AVG(gmv_eur)", True), ("SUM(total_amount)", False)):
        ov = bind_overrides(OntologyOverride(target_kind="metric", target_id="m",
                                             fields={"entity": "Order", "formula_sql": formula}), graph, explain)
        assert ov.sql_field_ok("formula_sql") is bound, formula
