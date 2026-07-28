"""Wave G5 — permission-trimmed retrieval, and the notice that keeps it honest.

The two carrying tests are :func:`test_a_trim_always_produces_a_notice` (an empty answer
teaches its reader the data does not exist) and
:func:`test_an_edge_across_the_boundary_is_swept` (the edge leaks the protected name in
the most load-bearing position there is).
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.govern.retrieval_trim import (
    caller_clearances,
    clearance_context,
    partition,
    securable_for_table,
    sweep_edges,
)
from aughor.govern.tags import ClearanceDecision, Requirement


def _node(nid: str, kind: str = "table", label: str = "",
          source_tables: list[str] | None = None) -> SimpleNamespace:
    """A graph node.

    ``source_tables`` defaults to the label rather than being omitted, because the real
    projection always carries it and a fixture that omits it is what let the label-based
    resolution bug pass every test in this file.
    """
    lbl = label or nid.split(":")[-1]
    return SimpleNamespace(
        id=nid, kind=kind, label=lbl,
        data={"source_tables": source_tables if source_tables is not None else [lbl]})


def _edge(from_id: str, to_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=f"{from_id}->{to_id}", from_id=from_id, to_id=to_id)


def _blocked(securable: str, clearance: str = "clearance.restricted") -> ClearanceDecision:
    req = Requirement(key="tier", value="restricted", clearance=clearance)
    return ClearanceDecision(securable=securable, allowed=False,
                             requirements=[req], missing=[req])


def _allowed(securable: str) -> ClearanceDecision:
    return ClearanceDecision(securable=securable, allowed=True)


def _checker(blocked_securables: set[str]):
    def check(securable, held):
        return (_blocked(securable) if securable in blocked_securables
                else _allowed(securable))
    return check


# ── partition ───────────────────────────────────────────────────────────────────────

def test_allowed_items_survive():
    r = partition([_node("table:orders")], lambda n: "table:c.s.orders", [],
                  check=_checker(set()))
    assert len(r.kept) == 1 and not r.trimmed


def test_blocked_items_are_withheld():
    r = partition([_node("table:salaries")], lambda n: "table:c.s.salaries", [],
                  check=_checker({"table:c.s.salaries"}))
    assert r.withheld and not r.kept and r.trimmed


def test_an_item_with_no_securable_passes_through():
    """Not every retrieved item is about a governed object."""
    r = partition([_node("metric:gmv", kind="metric")], lambda n: None, [],
                  check=_checker({"anything"}))
    assert len(r.kept) == 1


def test_an_unresolvable_securable_is_kept_not_withheld():
    """Failing closed on a name we cannot resolve would make enabling the flag a
    platform-wide outage rather than a policy — the same default G2 chose."""
    r = partition([_node("table:mystery")], lambda n: "", [], check=_checker({""}))
    assert len(r.kept) == 1 and not r.trimmed


def test_a_trim_always_produces_a_notice():
    """The pinned anti-pattern: a trimmed answer that comes back empty teaches its reader
    that the data does not exist. Withhold the rows, never the fact of withholding."""
    r = partition([_node("table:salaries")], lambda n: "table:c.s.salaries", [],
                  check=_checker({"table:c.s.salaries"}))
    notice = r.notice()
    assert notice
    assert "withheld by data governance" in notice
    assert "clearance.restricted" in notice


def test_the_notice_does_not_name_the_object_it_protected():
    """Telling the reader that `salaries` exists is what the tag was protecting."""
    r = partition([_node("table:salaries")], lambda n: "table:c.s.salaries", [],
                  check=_checker({"table:c.s.salaries"}))
    assert "salaries" not in r.notice()


def test_no_trim_means_no_notice():
    r = partition([_node("table:orders")], lambda n: "table:c.s.orders", [],
                  check=_checker(set()))
    assert r.notice() == ""


def test_the_notice_counts_correctly_and_dedupes_clearances():
    items = [_node(f"table:t{i}") for i in range(3)]
    r = partition(items, lambda n: f"table:c.s.{n.label}", [],
                  check=_checker({"table:c.s.t0", "table:c.s.t1", "table:c.s.t2"}))
    assert "3 items withheld" in r.notice()
    assert r.notice().count("clearance.restricted") == 1


def test_the_result_serializes_for_a_receipt():
    r = partition([_node("table:salaries")], lambda n: "table:c.s.salaries", [],
                  check=_checker({"table:c.s.salaries"}))
    d = r.to_dict()
    assert d["withheld"] == 1 and d["clearances_required"] == ["clearance.restricted"]


# ── the edge sweep is the actual boundary ───────────────────────────────────────────

def test_an_edge_across_the_boundary_is_swept():
    """A join edge names BOTH endpoints, so keeping it leaks the protected table's name
    as prompt ground truth — the exact leak the node trim exists to prevent."""
    edges = [_edge("table:orders", "table:salaries"), _edge("table:orders", "table:items")]
    kept = sweep_edges(edges, {"table:orders", "table:items"})
    assert [e.id for e in kept] == ["table:orders->table:items"]


def test_an_edge_wholly_inside_the_kept_set_survives():
    edges = [_edge("a", "b")]
    assert len(sweep_edges(edges, {"a", "b"})) == 1


def test_sweeping_against_an_empty_kept_set_drops_everything():
    assert sweep_edges([_edge("a", "b")], set()) == []


# ── the securable vocabulary ────────────────────────────────────────────────────────

def test_a_table_node_maps_into_the_metastore_vocabulary():
    assert securable_for_table("conn", "main", "orders") == "table:conn.main.orders"


def test_a_qualified_label_is_reduced_to_its_bare_name():
    assert securable_for_table("conn", "main", "luxexperience.orders") == \
        "table:conn.main.orders"


# ── the clearance context ───────────────────────────────────────────────────────────

def test_no_context_means_no_clearances():
    assert caller_clearances() == []


def test_the_context_supplies_clearances_and_restores_after():
    with clearance_context(["clearance.pii"]):
        assert caller_clearances() == ["clearance.pii"]
    assert caller_clearances() == []


def test_blank_clearances_are_ignored():
    with clearance_context(["", "  ", "clearance.pii"]):
        assert caller_clearances() == ["clearance.pii"]


# ── the read-back wiring ────────────────────────────────────────────────────────────

def test_readback_trim_is_a_no_op_when_governance_is_off(monkeypatch):
    """Byte-identical with the flag off — the retrieval path must not change at all."""
    from aughor.govern import tags as T
    from aughor.ontology import context_graph_readback as RB

    monkeypatch.setattr(T, "enabled", lambda: False)
    nodes = [_node("table:orders")]
    edges = [_edge("table:orders", "table:orders")]
    out_nodes, out_edges, notice = RB._trim_by_clearance(
        nodes, edges, connection_id="c", schema_name="s")
    assert out_nodes is nodes and out_edges is edges and notice == ""


def test_readback_trim_withholds_and_sweeps(monkeypatch):
    from aughor.govern import tags as T
    from aughor.ontology import context_graph_readback as RB

    monkeypatch.setattr(T, "enabled", lambda: True)
    monkeypatch.setattr(
        T, "check",
        lambda securable, held, bypass=False: (
            _blocked(securable) if securable.endswith("salaries") else _allowed(securable)))

    nodes = [_node("table:orders"), _node("table:salaries")]
    edges = [_edge("table:orders", "table:salaries")]
    out_nodes, out_edges, notice = RB._trim_by_clearance(
        nodes, edges, connection_id="c", schema_name="s")

    assert [n.id for n in out_nodes] == ["table:orders"]
    assert out_edges == []            # the cross-boundary edge is gone
    assert "withheld by data governance" in notice


def test_a_fully_trimmed_slice_still_returns_the_notice(monkeypatch):
    """The sharpest case: everything was withheld, so the prior would otherwise be empty
    and read exactly like 'the graph knew nothing'."""
    from aughor.govern import tags as T
    from aughor.ontology import context_graph_readback as RB

    monkeypatch.setattr(T, "enabled", lambda: True)
    monkeypatch.setattr(T, "check",
                        lambda securable, held, bypass=False: _blocked(securable))
    out_nodes, _, notice = RB._trim_by_clearance(
        [_node("table:salaries")], [], connection_id="c", schema_name="s")
    assert out_nodes == [] and notice


# ── several securables per item is the normal case ──────────────────────────────────

def test_an_item_backed_by_several_tables_is_withheld_if_ANY_is_blocked():
    """A graph table node is an ontology ENTITY, and an entity can be backed by more than
    one physical table. Showing an entity whose backing table is restricted shows the
    restricted thing."""
    item = _node("table:Sales")
    r = partition([item], lambda n: ["table:c.s.orders", "table:c.s.salaries"], [],
                  check=_checker({"table:c.s.salaries"}))
    assert r.withheld == [item] and not r.kept


def test_an_item_backed_by_several_allowed_tables_survives():
    r = partition([_node("table:Sales")],
                  lambda n: ["table:c.s.orders", "table:c.s.items"], [],
                  check=_checker(set()))
    assert len(r.kept) == 1 and not r.trimmed


def test_a_single_securable_string_is_still_accepted():
    """Backwards-compatible with the one-securable callers."""
    r = partition([_node("table:orders")], lambda n: "table:c.s.orders", [],
                  check=_checker(set()))
    assert len(r.kept) == 1


def test_readback_resolves_securables_from_source_tables_not_the_label():
    """Regression, found by probing a real graph rather than by a test.

    The node's `label` is the ontology entity's DISPLAY NAME ("Return") while the
    securable names the PHYSICAL table ("returns"), so resolving from the label matched
    nothing and the trim silently never fired. Every unit test above builds nodes whose
    label happens to equal the table, which is precisely why they all passed.
    """
    import inspect

    from aughor.ontology import context_graph_readback as RB

    src = inspect.getsource(RB._trim_by_clearance)
    assert "source_tables" in src
    assert "node.label" not in src


def test_readback_trims_a_node_by_its_source_table(monkeypatch):
    from aughor.govern import tags as T
    from aughor.ontology import context_graph_readback as RB

    monkeypatch.setattr(T, "enabled", lambda: True)
    monkeypatch.setattr(
        T, "check",
        lambda securable, held, bypass=False: (
            _blocked(securable) if securable.endswith("returns") else _allowed(securable)))

    # label "Return" ≠ table "returns" — the shape that broke on the real graph.
    node = SimpleNamespace(id="table:Return", kind="table", label="Return",
                           data={"source_tables": ["returns"]})
    keep = SimpleNamespace(id="table:Order", kind="table", label="Order",
                           data={"source_tables": ["orders"]})
    out_nodes, _, notice = RB._trim_by_clearance(
        [node, keep], [], connection_id="workspace", schema_name="default")
    assert [n.id for n in out_nodes] == ["table:Order"]
    assert notice


def test_a_table_node_with_no_source_tables_is_kept(monkeypatch):
    from aughor.govern import tags as T
    from aughor.ontology import context_graph_readback as RB

    monkeypatch.setattr(T, "enabled", lambda: True)
    monkeypatch.setattr(T, "check",
                        lambda securable, held, bypass=False: _blocked(securable))
    node = SimpleNamespace(id="table:Ghost", kind="table", label="Ghost", data={})
    out_nodes, _, notice = RB._trim_by_clearance(
        [node], [], connection_id="c", schema_name="s")
    assert out_nodes == [node] and notice == ""
