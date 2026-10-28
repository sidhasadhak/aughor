"""Arc FA, FA-3 — reads per entity over thirty days, folded into what uses an entity (ROADMAP §3.60).

Before: an entity's page counted audited statements per calendar month and nothing else — no rolling window, no last
read, no readers, one entity at a time, and two entities read from one table counted each other's reads unsaid. Held
here: the window counts the last thirty days, today included; the last read is the newest statement's moment; readers
are the distinct people the session log names for the runs that issued them, and a read whose run it does not name is
counted and said, never given a reader; every entity of a scope is listed by those reads, the least read first, an
uncounted one last and saying why; a shared table is said beside each entity that reads it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from aughor.ontology import entity_uses as U
from aughor.ontology.models import OntologyGraph
from aughor.security.audit import AuditLogger

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
DAY = 86_400


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    fresh = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: fresh))
    return fresh


@pytest.fixture
def router(graph, monkeypatch):
    from aughor.routers import objects as R
    monkeypatch.setattr(R, "_served_graph", lambda conn, schema: graph)
    monkeypatch.setattr(R, "_accepted_edits", lambda conn: [])
    return R


def _ran(ledger, trace_id: str, person: str) -> None:
    ledger.session_event_insert({"trace_id": trace_id, "kind": "tool_call", "user_id": person})


def test_the_window_counts_thirty_days_with_the_last_read_and_who_read(ledger):
    conn = "usage-window-t"
    _ran(ledger, "run-a", "person:ana")
    _ran(ledger, "run-b", "person:ben")
    AuditLogger.log(connection_id=conn, sql="SELECT * FROM customers", trace_id="run-a")
    AuditLogger.log(connection_id=conn, sql="SELECT 1 FROM shop.customers", trace_id="run-a")
    AuditLogger.log(connection_id=conn, sql="SELECT 2 FROM customers", trace_id="run-b")
    AuditLogger.log(connection_id=conn, sql="SELECT 3 FROM customers", trace_id="")             # no run issued it
    AuditLogger.log(connection_id=conn, sql="SELECT 4 FROM customers", trace_id="run-unlogged")
    AuditLogger.log(connection_id=conn, sql="SELECT * FROM customers_archive", trace_id="run-a")  # not a whole word
    out = U.window_reads(conn, {"Customer": ["customers"], "Order": ["orders"]})
    customer = out["Customer"]
    assert (customer["days"], customer["reads"], customer["readers"], customer["unattributed"]) == (30, 5, 2, 2)
    assert customer["last_read"] and customer["last_read"][:10] == time.strftime("%Y-%m-%d", time.gmtime())
    assert "Who ran 2 of 5 is not recorded" in customer["readers_said"]
    assert out["Order"] == {"days": 30, "reads": 0, "last_read": None, "readers": 0, "unattributed": 0}
    later = U.window_reads(conn, {"Customer": ["customers"]}, now=time.time() + 31 * DAY)
    assert later["Customer"]["reads"] == 0                                     # thirty days on, they are outside
    inside = U.window_reads(conn, {"Customer": ["customers"]}, now=time.time() + 29 * DAY)
    assert inside["Customer"]["reads"] == 5                                    # the window counts today too


def test_an_unreadable_session_log_leaves_the_readers_unsaid_never_zero(ledger, monkeypatch):
    AuditLogger.log(connection_id="usage-nolog-t", sql="SELECT * FROM customers", trace_id="run-a")
    monkeypatch.setattr(type(ledger), "session_people", lambda self, ids, org_id=None: (_ for _ in ()).throw(OSError("x")))
    row = U.window_reads("usage-nolog-t", {"Customer": ["customers"]})["Customer"]
    assert (row["reads"], row["readers"], row["unattributed"]) == (1, None, None)
    assert "could not be read" in row["readers_said"]


def test_entity_tables_read_off_the_entity_are_the_tables_its_detail_lists(graph):
    from aughor.semantic.object_types import describe_object_type
    for eid, entity in graph.entities.items():
        assert U.entity_tables(entity) == U.bound_tables(describe_object_type(graph, entity)), eid


def test_every_entity_ranked_least_read_first_a_shared_table_said_and_the_uncounted_last(router, graph, ledger,
                                                                                         monkeypatch):
    conn = "usage-rank-t"
    graph.entities["Review"].backing.table = "customers"                       # two entities, one table
    graph.entities["Product"].backing = graph.entities["Product"].backing.model_copy(
        update={"kind": "query", "table": None, "sql": "SELECT * FROM products"})
    for sql in ("SELECT * FROM customers", "SELECT * FROM orders", "SELECT * FROM orders o JOIN order_items i"):
        AuditLogger.log(connection_id=conn, sql=sql)
    out = router.get_object_types_by_reads(conn, schema_name=None, window=30)
    assert out["path"] == "by_reads" and out["days"] == 30
    rows = {r["entity"]: r for r in out["entities"]}
    order = [r["entity"] for r in out["entities"]]
    assert order[-1] == "Product" and rows["Product"]["reads"] is None and "nothing is counted" in rows["Product"]["said"]
    counted = [r["reads"] for r in out["entities"] if r["reads"] is not None]
    assert counted == sorted(counted)                                          # the least read first
    assert (rows["Order"]["reads"], rows["OrderItem"]["reads"]) == (2, 1)
    assert rows["Customer"]["reads"] == rows["Review"]["reads"] == 1
    assert rows["Customer"]["shared"] == [{"table": "customers", "with": [graph.entities["Review"].display_name]}]
    assert "counts for" in rows["Review"]["shared_said"]
    assert rows["Order"]["shared"] == [] and "shared_said" not in rows["Order"]


def test_the_entity_door_carries_the_window_and_what_it_shares(router, graph, ledger, monkeypatch):
    monkeypatch.setattr("aughor.ontology.dependents.dependents_of", lambda *a, **k: [])
    monkeypatch.setattr("aughor.dashboards.pieces.dashboards_reading", lambda *a, **k: [])
    conn = "usage-door-t"
    graph.entities["Review"].backing.table = "customers"
    AuditLogger.log(connection_id=conn, sql="SELECT * FROM customers")
    out = router.get_object_type_uses("customer", conn, schema_name=None)
    window = out["reads"]["window"]
    assert (window["days"], window["reads"], window["readers"], window["unattributed"]) == (30, 1, 0, 1)
    assert out["reads"]["shared"] == [{"table": "customers", "with": [graph.entities["Review"].display_name]}]
    assert len(out["reads"]["months"]) == 12                                   # the twelve months stay


def test_the_list_has_its_own_address(router, client):
    # the list's address is its own door, never an entity called "uses"
    served = client.get("/object-types/uses", params={"connection_id": "usage-list-t", "window": 30})
    assert served.status_code == 200 and served.json()["path"] == "by_reads"
    assert client.get("/object-types/uses", params={"connection_id": "usage-list-t", "window": 0}).status_code == 422


def test_one_reading_of_each_statement_counts_every_entity_whose_table_it_names():
    """The log is read once for every entity: a statement counts for each entity owning a table it names as a whole word,
    whatever its case — a name inside a longer one is not a read of it, and one table two entities share counts both."""
    conn = "usage-one-pass-t"
    AuditLogger.log(connection_id=conn, sql="SELECT * FROM ORDERS o JOIN order_items i ON o.id = i.order_id")
    AuditLogger.log(connection_id=conn, sql="SELECT * FROM order_items")
    AuditLogger.log(connection_id=conn, sql="select * from Events")
    AuditLogger.log(connection_id=conn, sql="SELECT * FROM orders_archive")
    got = AuditLogger.reads_within(conn, {"Order": ["orders"], "OrderItem": ["order_items"], "Event": ["events"],
                                         "User": ["users", "events"], "Unbound": []})
    assert {k: v["reads"] for k, v in got.items()} == {"Order": 1, "OrderItem": 2, "Event": 1, "User": 1, "Unbound": 0}
