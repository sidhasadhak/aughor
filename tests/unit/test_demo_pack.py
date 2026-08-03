"""The demo pack exporter — the connection filter, the round trip, the version gate.

The filter is the reason this module has tests at all. The reference store held 724
investigations, 670 of them real business data belonging to an unrelated connection; a
pack that quietly skipped a foreign row would report success while having been asked to
do the one thing it must never do. So the refusal is tested before anything else.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aughor.demo.pack import (
    PACK_VERSION,
    Pack,
    PackError,
    export_pack,
    pack_round_trips,
    read_pack,
    write_pack,
)


def _inv(inv_id: str, conn: str, *, status: str = "complete", started: str = "2026-01-01") -> dict:
    return {
        "id": inv_id, "question": f"q for {inv_id}", "connection_id": conn,
        "started_at": started, "completed_at": started, "status": status,
        "hypothesis_count": 0, "query_count": 2, "headline": f"headline {inv_id}",
        "kind": "investigation", "canvas_id": None, "purpose": "",
        "report": {"headline": f"headline {inv_id}", "phases": []},
        "hypotheses": [], "query_history": [{"sql": "SELECT 1"}],
    }


@pytest.fixture
def stub_history(monkeypatch):
    """A two-connection history: `demo` is exportable, `private` must never travel."""
    rows = {
        "a1": _inv("a1", "demo", started="2026-01-03"),
        "a2": _inv("a2", "demo", started="2026-01-02"),
        "a3": _inv("a3", "demo", status="running", started="2026-01-01"),
        "p1": _inv("p1", "private", started="2026-01-04"),
    }
    import aughor.db.history as H
    monkeypatch.setattr(H, "get_investigation", lambda i: rows.get(i))
    monkeypatch.setattr(H, "list_investigation_ids",
                        lambda conn, *a, **k: [i for i, r in rows.items() if r["connection_id"] == conn])
    # Curation/graph are separately-owned surfaces; pin them so these tests are about
    # the pack, not about whichever stores happen to exist on the box.
    import aughor.demo.pack as P
    monkeypatch.setattr(P, "_collect_curation", lambda c: {"synonyms": [{"term": "rev"}]})
    monkeypatch.setattr(P, "_collect_graph", lambda c, invs: {"nodes": [], "edges": []})
    return rows


# ── the safety gate ───────────────────────────────────────────────────────────

def test_a_foreign_investigation_aborts_the_export(stub_history, tmp_path):
    """Naming another connection's row is an ERROR, not a silently filtered one.

    Skipping would be the dangerous behaviour: the export would succeed, the operator
    would see a pack, and the only evidence of the near-miss would be a count nobody
    checked."""
    with pytest.raises(PackError) as exc:
        export_pack("demo", tmp_path, investigation_ids=["a1", "p1"])
    assert "p1" in str(exc.value) and "private" in str(exc.value)


def test_an_unfiltered_export_carries_only_its_own_connection(stub_history, tmp_path):
    pack = export_pack("demo", tmp_path)
    assert {i["id"] for i in pack.investigations} == {"a1", "a2"}     # a3 is unfinished
    assert all(i["connection_id"] == "demo" for i in pack.investigations)
    on_disk = (tmp_path / "investigations").glob("*.json")
    assert "p1.json" not in {p.name for p in on_disk}


def test_export_requires_a_connection(tmp_path):
    """No connection means no scope, and an unscoped pack is the leak this prevents."""
    with pytest.raises(PackError):
        export_pack("", tmp_path)


def test_an_unfinished_investigation_is_not_an_artifact(stub_history, tmp_path):
    pack = export_pack("demo", tmp_path)
    assert "a3" not in {i["id"] for i in pack.investigations}


# ── the round trip ────────────────────────────────────────────────────────────

def test_export_then_read_preserves_the_content(stub_history, tmp_path):
    written = export_pack("demo", tmp_path)
    loaded = read_pack(tmp_path)
    assert loaded.connection_id == written.connection_id
    assert [i["id"] for i in loaded.investigations] == [i["id"] for i in written.investigations]
    assert loaded.curation == written.curation
    assert loaded.graph == written.graph


def test_the_pack_round_trips_byte_for_byte(stub_history, tmp_path):
    """`interchange.py` sets this bar: 'a lossy round-trip is worse than no interchange at
    all: it looks like a backup'. A pack that drops a finding on re-bake still opens,
    still renders, and is still wrong."""
    export_pack("demo", tmp_path)
    assert pack_round_trips(tmp_path) is True


def test_a_tampered_pack_fails_the_round_trip(stub_history, tmp_path):
    """The gate has to be able to FAIL, or it is decoration.

    Deleting one investigation is caught by the ENVELOPE rather than by the missing file:
    pack.json still claims two, a re-write from the diminished read declares one, and the
    bytes diverge. That is the property worth having — a pack whose manifest disagrees
    with its contents is exactly the "looks like a backup" failure the round trip exists
    to refuse, and it would otherwise open and render perfectly."""
    export_pack("demo", tmp_path)
    assert pack_round_trips(tmp_path) is True

    next((tmp_path / "investigations").glob("*.json")).unlink()
    assert len(read_pack(tmp_path).investigations) == 1    # the loss is readable…
    assert pack_round_trips(tmp_path) is False             # …and the gate refuses it


# ── the version gate ──────────────────────────────────────────────────────────

def test_a_future_pack_is_refused_rather_than_mis_read(stub_history, tmp_path):
    export_pack("demo", tmp_path)
    env = json.loads((tmp_path / "pack.json").read_text())
    env["version"] = PACK_VERSION + 1
    (tmp_path / "pack.json").write_text(json.dumps(env))
    with pytest.raises(PackError) as exc:
        read_pack(tmp_path)
    assert "Refusing" in str(exc.value)


def test_a_directory_that_is_not_a_pack_is_refused(tmp_path):
    with pytest.raises(PackError):
        read_pack(tmp_path)


def test_the_envelope_reports_what_travelled(stub_history, tmp_path):
    pack = export_pack("demo", tmp_path)
    env = json.loads((tmp_path / "pack.json").read_text())
    assert env["connection_id"] == "demo"
    assert env["counts"]["investigations"] == len(pack.investigations) == 2
    assert env["counts"]["graph"] is True


def test_write_pack_is_deterministic(tmp_path):
    """Two writes of the same pack must be byte-identical or the round-trip gate is
    measuring dict ordering rather than content."""
    p = Pack(version=PACK_VERSION, connection_id="demo",
             investigations=[_inv("a1", "demo")], curation={"b": 1, "a": 2}, graph=None)
    write_pack(p, tmp_path / "one")
    write_pack(p, tmp_path / "two")
    assert (tmp_path / "one" / "curation.json").read_bytes() == \
           (tmp_path / "two" / "curation.json").read_bytes()


# ── The SHIPPED pack ──────────────────────────────────────────────────────────
# The design names a lossy re-bake as the second-worst risk: a pack regenerated after a
# schema change silently drops findings, and it would still open and still render. The
# round-trip gate is only a mitigation if it runs over the artifact that actually ships,
# so these tests read the committed pack rather than a fixture.

_SHIPPED = Path(__file__).resolve().parents[2] / "data" / "demo_packs" / "superstore"


def test_the_shipped_pack_round_trips():
    pack = read_pack(_SHIPPED)
    assert pack.investigations, "the shipped pack carries no investigations"
    assert pack_round_trips(_SHIPPED), (
        "the shipped demo pack no longer round-trips — a re-bake would lose content")


def test_the_shipped_pack_carries_exactly_one_connection():
    """The safety property, asserted on the artifact itself and not just the exporter.
    A public pack built from a store holding other workspaces' real business data is one
    stray id away from a leak."""
    pack = read_pack(_SHIPPED)
    owners = {i.get("connection_id") for i in pack.investigations}
    assert owners == {pack.connection_id}, f"pack mixes connections: {owners}"


def test_the_shipped_pack_ships_no_unfinished_run():
    pack = read_pack(_SHIPPED)
    assert all(i.get("status") == "complete" for i in pack.investigations)


def test_the_shipped_pack_measures_profit_not_a_proxy_for_it():
    """The pack is a showroom, so its own contents are the claim. Two pre-fix artifacts
    answered 'where are we losing money' with a discount-leakage RATE while `orders.profit`
    sat in the schema, and one abstained outright — curated out deliberately. This asserts
    they stay out: a deep analysis in the pack must report a direct loss measure.
    """
    pack = read_pack(_SHIPPED)
    deep = [i for i in pack.investigations if (i.get("kind") or "") != "chat"]
    assert deep, "the pack carries no deep analysis"
    for inv in deep:
        metric = ((inv.get("report") or {}).get("metric") or "").lower()
        assert any(w in metric for w in ("profit", "margin", "cost")), (
            f"{inv['id']} reports {metric!r} — a proxy, not the loss measure the question asks about")


def test_the_shipped_pack_contains_no_rate_times_count_contra_amount():
    """`SUM(discount * quantity)` multiplies a rate by a unit count. It shipped once,
    understating contra-revenue 140× and reading as 'leakage is negligible'. Pinned here
    because the pack is the artifact a visitor actually reads."""
    blob = json.dumps([i.get("report") for i in read_pack(_SHIPPED).investigations], default=str)
    assert "discount * quantity" not in blob
    assert "quantity * discount" not in blob


# ── Graph scoping ─────────────────────────────────────────────────────────────
# Measured on the Superstore demo: the glossary store held ~230 table keys spanning
# TPC-H, TPC-DS, an airline schema and two retail workspaces, with ZERO per-connection
# overlays. The projection's scoping matches on table NAME, so the connection's bare
# `orders` matched a different dataset's `orders` and 48 of 75 terms in the built graph
# were foreign. Separately, the projection reads every receipt on the connection, so a
# graph built beside a CURATED pack re-imported runs the curation had dropped.

class _N:
    def __init__(self, kind, data=None, summary="", source=""):
        self.kind, self.data, self.summary = kind, data or {}, summary
        self.provenance = type("P", (), {"source": source})()


class _E:
    def __init__(self, from_id, to_id):
        self.from_id, self.to_id = from_id, to_id


class _G:
    def __init__(self, nodes, edges=None):
        self.nodes, self.edges = nodes, edges or {}


def _graph_with_foreign_terms():
    return _G({
        "glossary_term:orders.sales":     _N("glossary_term", {"table": "orders", "column": "sales"}),
        "glossary_term:orders.duty_eur":  _N("glossary_term", {"table": "orders", "column": "duty_eur"}),
        "glossary_term:orders.o_orderkey": _N("glossary_term", {"table": "orders", "column": "o_orderkey"}),
        "table:Order": _N("table"),
    }, {
        "e_ok":      _E("table:Order", "glossary_term:orders.sales"),
        "e_foreign": _E("table:Order", "glossary_term:orders.duty_eur"),
    })


def test_a_term_whose_column_this_connection_lacks_is_dropped(monkeypatch):
    from aughor.demo import pack as P
    monkeypatch.setattr(P, "_connection_columns",
                        lambda _c: {"orders": {"sales", "discount", "profit"}})
    g = P._scope_graph_to_pack(_graph_with_foreign_terms(), "8d36d4c2", [])
    assert set(g.nodes) == {"glossary_term:orders.sales", "table:Order"}


def test_an_edge_to_a_dropped_term_does_not_dangle(monkeypatch):
    from aughor.demo import pack as P
    monkeypatch.setattr(P, "_connection_columns", lambda _c: {"orders": {"sales"}})
    g = P._scope_graph_to_pack(_graph_with_foreign_terms(), "8d36d4c2", [])
    assert set(g.edges) == {"e_ok"}


def test_an_unreadable_schema_drops_the_whole_glossary_slice(monkeypatch):
    """Default-deny. 'Unknown' must not be treated as 'fine' — the same posture the
    connection filter takes, for the same reason."""
    from aughor.demo import pack as P
    monkeypatch.setattr(P, "_connection_columns", lambda _c: None)
    g = P._scope_graph_to_pack(_graph_with_foreign_terms(), "8d36d4c2", [])
    assert not [n for n in g.nodes.values() if n.kind == "glossary_term"]
    assert "table:Order" in g.nodes          # every other slice survives


def test_a_finding_from_an_investigation_the_pack_dropped_does_not_travel(monkeypatch):
    from aughor.demo import pack as P
    monkeypatch.setattr(P, "_connection_columns", lambda _c: {})
    g = _G({
        "keep": _N("finding", summary="Tables losses are concentrated in East.",
                   source="evidence_ledger"),
        "drop": _N("finding", summary="Discount leakage is highest in Ohio, Machines.",
                   source="evidence_ledger"),
        "explorer": _N("finding", summary="Some explorer finding.", source="exploration"),
    })
    P._scope_graph_to_pack(g, "8d36d4c2",
                           [{"headline": "Tables losses are concentrated in East."}])
    assert set(g.nodes) == {"keep", "explorer"}, (
        "receipt findings must follow the pack's curation; explorer findings are unaffected")


def test_schema_columns_parses_the_rendered_schema():
    from aughor.demo.pack import _schema_columns
    cols = _schema_columns("TABLE: orders\n  sales DOUBLE\n  discount DOUBLE\nTABLE: returns\n  order_id VARCHAR\n")
    assert cols == {"orders": {"sales", "discount"}, "returns": {"order_id"}}


def test_the_shipped_pack_graph_carries_no_foreign_glossary_term():
    """The artifact itself, not just the filter. A public pack carrying another
    workspace's column semantics is the risk this module exists to prevent."""
    graph = read_pack(_SHIPPED).graph
    assert graph, "the shipped pack has no graph"
    blob = json.dumps(graph).lower()
    for foreign in ("duty_eur", "gmv_eur", "o_orderkey", "coupon_abuse", "luxexperience"):
        assert foreign not in blob, f"{foreign!r} leaked into the shipped pack graph"


def test_the_shipped_pack_graph_agrees_with_its_own_investigations():
    """A finding node naming a run the pack dropped would reintroduce it sideways."""
    pack = read_pack(_SHIPPED)
    headlines = {(i.get("headline") or "").strip().lower() for i in pack.investigations}
    nodes = pack.graph.get("nodes") if isinstance(pack.graph, dict) else None
    nodes = list(nodes.values()) if isinstance(nodes, dict) else (nodes or [])
    receipts = [n for n in nodes if n.get("kind") == "finding"
                and ((n.get("provenance") or {}).get("source")) == "evidence_ledger"]
    assert receipts, "no receipt-sourced findings — the join key would be untested"
    for n in receipts:
        assert (n.get("summary") or "").strip().lower() in headlines, (
            f"graph carries {n.get('summary')!r}, from an investigation the pack dropped")
