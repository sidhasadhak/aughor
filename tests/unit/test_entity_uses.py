"""ROADMAP §6 item 53 — what an entity is used by, on its own page, behind `ontology.entity_usage`.

Held here: off, the door says it is off and the type's detail is byte-for-byte what it was; on, the door
composes the dependents index and the dashboards door with the arguments they expect, and counts the audited
statements that named the entity's tables month by month — a whole-word match, so a read of `customers_archive`
is not a read of `customers`, while `shop.customers` is; a table-less type counts nothing and says so.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aughor.ontology.models import OntologyGraph
from aughor.security.audit import AuditLogger

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
CONN = "uses-t"


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture
def router(graph, monkeypatch):
    from aughor.routers import objects as R
    monkeypatch.setattr(R, "_served_graph", lambda conn, schema: graph)
    monkeypatch.setattr(R, "_accepted_edits", lambda conn: [])
    return R


def _on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.entity_usage")


def test_off_the_door_says_so_and_the_detail_is_what_it_was(router):
    assert router.get_object_type_uses("customer", CONN, schema_name=None) == {
        "path": "off", "said": "What uses an entity is not shown: the setting is off."}
    detail = router.get_object_type("customer", CONN, schema_name=None, domain=None)
    assert detail["path"] == "object_type"
    assert not {"uses", "dependents", "dashboards", "reads"} & set(detail)


def test_on_it_composes_the_two_doors_with_the_entity_and_counts_its_tables_by_month(router, graph, monkeypatch):
    _on(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr("aughor.ontology.dependents.dependents_of",
                        lambda g, conn, kind, target, **kw: seen.setdefault("dependents", (conn, kind, target)) and [
                            {"consumer": "rule", "id": "vip", "name": "VIP customers", "how": "the rule is defined over it"}])
    monkeypatch.setattr("aughor.dashboards.pieces.dashboards_reading",
                        lambda conn, names, graph=None: seen.setdefault("dashboards", (conn, set(names))) and [
                            {"id": "late", "title": "Late orders", "pieces": ["t"]}])
    table = graph.entities["Customer"].backing.table.rsplit(".", 1)[-1]
    for sql in (f"SELECT COUNT(*) FROM {table}", f"SELECT 1 FROM shop.{table} WHERE 1=1"):
        AuditLogger.log(connection_id=CONN, sql=sql)
    AuditLogger.log(connection_id=CONN, sql=f"SELECT * FROM {table}_archive")        # not a whole word
    AuditLogger.log(connection_id="someone-else", sql=f"SELECT * FROM {table}")       # another connection
    out = router.get_object_type_uses("customer", CONN, schema_name=None)
    assert out["path"] == "uses" and out["entity"] == "Customer"
    assert seen["dependents"] == (CONN, "entity", "Customer")
    assert seen["dashboards"][0] == CONN and {"Customer"} <= seen["dashboards"][1]
    assert out["dependents"] == [{"consumer": "rule", "id": "vip", "name": "VIP customers", "how": "the rule is defined over it"}]
    assert out["dashboards"] == [{"id": "late", "title": "Late orders", "pieces": ["t"]}]
    assert out["reads"]["tables"] == [table] and "said" not in out["reads"]
    months = out["reads"]["months"]
    assert len(months) == 12 and months[-1]["reads"] == 2 and sum(m["reads"] for m in months[:-1]) == 0
    assert all(len(m["month"]) == 7 for m in months) and months == sorted(months, key=lambda m: m["month"])


def test_reads_by_month_keeps_every_month_of_the_window_and_only_this_connection():
    AuditLogger.log(connection_id="window-t", sql="SELECT * FROM orders")
    months = AuditLogger.reads_by_month("window-t", ["orders"], months=3, now=1_800_000_000)   # 2027-01-15 UTC
    assert [m["month"] for m in months] == ["2026-11", "2026-12", "2027-01"]
    assert sum(m["reads"] for m in months) == 0                       # the row was stamped today, outside that window
    assert AuditLogger.reads_by_month("window-t", [], months=2) == [
        {"month": m["month"], "reads": 0} for m in AuditLogger.reads_by_month("window-t", ["orders"], months=2)]


def test_a_type_with_no_bound_table_counts_nothing_and_says_so(graph, monkeypatch):
    from aughor.ontology import entity_uses
    monkeypatch.setattr("aughor.ontology.dependents.dependents_of", lambda *a, **k: [])
    monkeypatch.setattr("aughor.dashboards.pieces.dashboards_reading", lambda *a, **k: [])
    out = entity_uses.uses_of(graph, CONN, {"id": "Ghost", "bindings": []})
    assert out["reads"] == {"tables": [], "months": [], "source": "the platform's log of statements run",
                            "said": "No table is bound to it, so nothing is counted."}


def test_an_unknown_type_is_refused_as_the_detail_refuses_it(router, monkeypatch):
    _on(monkeypatch)
    out = router.get_object_type_uses("unicorn", CONN, schema_name=None)
    assert out["path"] == "refused" and out["connection_id"] == CONN
