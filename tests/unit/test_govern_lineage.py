"""Wave G7 — lineage-aware dependency reporting, and the connector credential audit.

Two halves. The lineage walk answers "what is derived from this table" from edges the
graph already records and nobody was querying. The credential audit is a RATCHET over a
finding rather than a fix: both knowledge connectors authenticate with one shared service
token, which is not the per-user-OAuth rule the program asked for, and pretending otherwise
would be worse than recording it.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.govern.lineage import (
    LINEAGE_EDGES,
    MAX_DEPTH,
    LineageReport,
    dependents_of,
)


def _n(nid: str, kind: str, label: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=nid, kind=kind, label=label or nid)


def _e(from_id: str, to_id: str, kind: str = "grounded_in") -> SimpleNamespace:
    return SimpleNamespace(id=f"{from_id}-{kind}->{to_id}", from_id=from_id,
                           to_id=to_id, kind=kind)


def _graph(nodes, edges):
    return SimpleNamespace(nodes={n.id: n for n in nodes}, edges=edges)


# ── the walk ────────────────────────────────────────────────────────────────────────

def test_a_finding_grounded_in_a_table_is_a_dependent():
    g = _graph([_n("table:orders", "table"), _n("finding:f1", "finding", "GMV is 45M")],
               [_e("finding:f1", "table:orders")])
    r = dependents_of(g, "table:orders")
    assert [d.node_id for d in r.dependents] == ["finding:f1"]
    assert r.dependents[0].via == "grounded_in" and r.dependents[0].depth == 1


def test_lineage_is_transitive():
    """A brief derives from a finding which grounds in a table — the shape that makes a
    single-hop answer wrong."""
    g = _graph(
        [_n("table:orders", "table"), _n("finding:f1", "finding"), _n("brief:b1", "brief")],
        [_e("finding:f1", "table:orders"), _e("brief:b1", "finding:f1", "derived_from")])
    r = dependents_of(g, "table:orders")
    assert {d.node_id for d in r.dependents} == {"finding:f1", "brief:b1"}
    assert {d.depth for d in r.dependents} == {1, 2}


def test_only_lineage_edges_are_walked():
    """A join edge means two tables relate, NOT that one derives from the other. Walking
    it would report every joinable table as a dependent of every other."""
    g = _graph([_n("table:orders", "table"), _n("table:items", "table")],
               [_e("table:items", "table:orders", "joins_on")])
    assert dependents_of(g, "table:orders").dependents == []


def test_edges_are_walked_in_the_right_direction():
    """`grounded_in` points finding → table. Asking about the FINDING must not return
    the table."""
    g = _graph([_n("table:orders", "table"), _n("finding:f1", "finding")],
               [_e("finding:f1", "table:orders")])
    assert dependents_of(g, "finding:f1").dependents == []


def test_a_cycle_terminates():
    g = _graph([_n("a", "finding"), _n("b", "finding")],
               [_e("a", "b", "derived_from"), _e("b", "a", "derived_from")])
    r = dependents_of(g, "a")
    assert [d.node_id for d in r.dependents] == ["b"]


def test_the_walk_is_depth_bounded_and_says_so():
    """A bounded count presented as exact is how a delete preview under-reports what a
    deletion will orphan."""
    nodes = [_n(f"n{i}", "finding") for i in range(MAX_DEPTH + 3)]
    edges = [_e(f"n{i + 1}", f"n{i}", "derived_from") for i in range(MAX_DEPTH + 2)]
    r = dependents_of(_graph(nodes, edges), "n0", max_depth=2)
    assert len(r.dependents) == 2
    assert r.truncated
    assert r.summary().startswith("At least ")


def test_an_exhausted_walk_is_not_marked_truncated():
    g = _graph([_n("table:orders", "table"), _n("finding:f1", "finding")],
               [_e("finding:f1", "table:orders")])
    r = dependents_of(g, "table:orders")
    assert not r.truncated and not r.summary().startswith("At least")


def test_an_empty_or_missing_graph_reports_nothing():
    assert dependents_of(None, "table:orders").dependents == []
    assert dependents_of(_graph([], []), "table:orders").dependents == []


def test_an_edge_to_a_node_that_is_not_in_the_graph_is_skipped():
    g = _graph([_n("table:orders", "table")], [_e("finding:ghost", "table:orders")])
    assert dependents_of(g, "table:orders").dependents == []


# ── reporting, never deleting ───────────────────────────────────────────────────────

def test_the_module_exposes_no_delete():
    """A lineage walk that deleted would quietly become the most destructive path in the
    platform, reachable from a single table drop. C1's supersede-not-delete rule stands."""
    import aughor.govern.lineage as L

    assert not [n for n in dir(L)
                if any(w in n.lower() for w in ("delete", "purge", "remove", "drop"))]


def test_the_summary_says_the_dependents_are_reported_not_removed():
    g = _graph([_n("table:orders", "table"), _n("finding:f1", "finding")],
               [_e("finding:f1", "table:orders")])
    assert "reported, not removed" in dependents_of(g, "table:orders").summary()


def test_an_empty_report_says_so_plainly():
    assert "Nothing in the graph" in LineageReport(root="table:x").summary()


def test_counts_are_grouped_by_kind():
    g = _graph(
        [_n("table:orders", "table"), _n("finding:f1", "finding"),
         _n("finding:f2", "finding"), _n("metric:gmv", "metric")],
        [_e("finding:f1", "table:orders"), _e("finding:f2", "table:orders"),
         _e("metric:gmv", "table:orders", "derived_from")])
    r = dependents_of(g, "table:orders")
    assert r.counts_by_kind == {"finding": 2, "metric": 1}
    assert r.to_dict()["counts_by_kind"]["finding"] == 2


def test_the_lineage_edge_set_is_stated():
    assert LINEAGE_EDGES == {"grounded_in", "derived_from"}


# ── the connector credential audit ──────────────────────────────────────────────────

class TestKnowledgeConnectorCredentials:
    """G7's audit half, recorded as a ratchet over the ACTUAL state.

    The program asked that knowledge connectors follow the per-user-OAuth rule. They do
    not: both authenticate with one shared service token held in connection ``meta``, so
    every user of a Notion or Confluence connection reads exactly what that token can
    read, regardless of their own permissions in the source system.

    Converting them is an OAuth-app project well beyond this wave. Recording the finding
    as a test is the honest alternative to a docstring nobody re-reads — and it fails if a
    THIRD knowledge connector is added, which is the moment to decide the credential model
    rather than inheriting this one by default.
    """

    def test_the_known_knowledge_connectors_are_exactly_these_two(self):
        import pathlib

        import aughor.connectors.knowledge as pkg

        mods = sorted(p.stem for p in pathlib.Path(pkg.__file__).parent.glob("*.py")
                      if p.stem != "__init__")
        assert mods == ["confluence", "notion"], (
            "a knowledge connector was added or removed — decide its credential model "
            "explicitly (per-user OAuth, or a declared shared-token exception) rather "
            "than inheriting the shared-token default these two use")

    def test_both_authenticate_with_a_shared_service_token_today(self):
        """The finding itself, asserted rather than described."""
        import inspect

        from aughor.connectors.knowledge import confluence, notion

        assert "api_token" in inspect.getsource(confluence)
        assert "integration_token" in inspect.getsource(notion)

    def test_neither_claims_per_user_oauth(self):
        """Guards against a future edit that adds the words without the mechanism."""
        import inspect

        from aughor.connectors.knowledge import confluence, notion

        for mod in (confluence, notion):
            src = inspect.getsource(mod).lower()
            if "oauth" in src:
                assert "per-user" in src or "per_user" in src, (
                    f"{mod.__name__} mentions OAuth without saying whose credential it "
                    f"uses — the ambiguity is the bug")
