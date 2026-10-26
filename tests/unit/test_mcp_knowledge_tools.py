"""Wave S6 — the knowledge tools, and the clearance boundary they must not be a hole in.

The carrying test is :class:`TestClearanceOnTheExternalSurface`. MCP is an *external agent*
surface: `search_graph` returns node labels and `describe_entity` returns a table's columns
and joins — the same table-derived facts G5 spent a wave trimming out of prompts. Skipping
the trim here is a bigger hole than skipping it internally, because the consumer is not a
person who might notice something looks wrong.

Second: :func:`test_no_checks_run_is_not_the_same_as_healthy`. An agent reads a bare
"healthy" as a fact and repeats it confidently.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.mcp.knowledge_tools import (
    describe_entity,
    get_table_health,
    list_trusted_queries,
    search_graph,
)


@pytest.fixture(autouse=True)
def quality_db(tmp_path, monkeypatch):
    import aughor.quality.results as R

    monkeypatch.setattr(R, "_DB_PATH", tmp_path / "quality.db")


@pytest.fixture(autouse=True)
def no_ontology(monkeypatch):
    """These tests pin the knowledge graph's fallback: no ontology is served, so `describe_entity` reads the
    table node. The object-type path is `test_describe_entity_object_type.py`'s."""
    import aughor.mcp.knowledge_tools as KT

    monkeypatch.setattr(KT, "_served_ontology", lambda *a, **k: None)


def _node(nid, kind="table", label="", sources=None):
    return SimpleNamespace(id=nid, kind=kind, label=label or nid.split(":")[-1],
                           summary="", data={"source_tables": sources
                                             if sources is not None else [label or nid]})


def _graph(nodes, edges=()):
    return SimpleNamespace(nodes={n.id: n for n in nodes}, edges=list(edges))


def _patch_graph(monkeypatch, graph):
    import aughor.mcp.knowledge_tools as KT

    monkeypatch.setattr(KT, "_load_graph", lambda *a, **k: graph)


# ── no graph is said, not implied ───────────────────────────────────────────────────

def test_no_graph_reports_unavailable_with_a_reason(monkeypatch):
    _patch_graph(monkeypatch, None)
    out = search_graph("c1", "orders")
    assert out["available"] is False and "no context graph" in out["reason"]


def test_no_such_entity_says_so(monkeypatch):
    _patch_graph(monkeypatch, _graph([_node("table:orders", label="orders")]))
    out = describe_entity("c1", "nonexistent")
    assert out["available"] is False and "nonexistent" in out["reason"]


# ── describe_entity ─────────────────────────────────────────────────────────────────

def test_describe_matches_on_the_physical_table(monkeypatch):
    """The label is the ENTITY display name and the securable names the physical table —
    the distinction that broke G5's first cut. Matching must accept both."""
    node = _node("table:Return", label="Return", sources=["returns"])
    _patch_graph(monkeypatch, _graph([node]))
    assert describe_entity("c1", "returns")["available"] is True
    assert describe_entity("c1", "Return")["available"] is True


def test_describe_returns_related_edges_with_their_measured_overlap(monkeypatch):
    a, b = _node("table:orders", label="orders"), _node("table:items", label="items")
    edge = SimpleNamespace(kind="joins_on", from_id="table:orders", to_id="table:items",
                           provenance=SimpleNamespace(measured=0.97, note="probed"))
    _patch_graph(monkeypatch, _graph([a, b], [edge]))
    out = describe_entity("c1", "orders")
    assert out["related"][0]["measured"] == 0.97


def test_a_qualified_name_is_normalised(monkeypatch):
    _patch_graph(monkeypatch, _graph([_node("table:orders", label="orders")]))
    assert describe_entity("c1", "shop.orders")["available"] is True


# ── the clearance boundary ──────────────────────────────────────────────────────────

class TestClearanceOnTheExternalSurface:
    def _block_salaries(self, monkeypatch):
        from aughor.govern import tags as T
        from aughor.govern.tags import ClearanceDecision, Requirement

        req = Requirement(key="tier", value="restricted",
                          clearance="clearance.restricted")
        monkeypatch.setattr(
            T, "check",
            lambda securable, held, bypass=False: (
                ClearanceDecision(securable=securable, allowed=False,
                                  requirements=[req], missing=[req])
                if "salaries" in securable
                else ClearanceDecision(securable=securable, allowed=True)))

    def test_search_withholds_a_restricted_table(self, monkeypatch):
        """The hole this test exists to prevent: an external agent asking the graph for
        everything and receiving what a clearance was protecting."""
        import aughor.mcp.knowledge_tools as KT

        self._block_salaries(monkeypatch)
        nodes = [_node("table:orders", label="orders"),
                 _node("table:salaries", label="salaries")]
        _patch_graph(monkeypatch, _graph(nodes))
        monkeypatch.setattr(KT, "_search_hits", None, raising=False)
        monkeypatch.setattr("aughor.ontology.context_graph_search.search_graph",
                            lambda g, q, top_k=10: [(n, 1.0) for n in nodes])

        out = search_graph("c1", "anything")
        assert [n["label"] for n in out["nodes"]] == ["orders"]
        assert "withheld by data governance" in out["notice"]

    def test_describe_withholds_and_says_so(self, monkeypatch):
        """An agent receiving a bare 'not found' would report that the table does not
        exist — confidently, and wrongly."""
        self._block_salaries(monkeypatch)
        _patch_graph(monkeypatch, _graph([_node("table:salaries", label="salaries")]))
        out = describe_entity("c1", "salaries")
        assert out["available"] is False
        assert "withheld" in out["reason"] and out["notice"]

    def test_the_notice_never_names_the_protected_object(self, monkeypatch):
        self._block_salaries(monkeypatch)
        _patch_graph(monkeypatch, _graph([_node("table:salaries", label="salaries")]))
        assert "salaries" not in describe_entity("c1", "salaries")["notice"]

    def _over_salaries(self, monkeypatch):
        """A graph where three kinds of node rest on the restricted table: a metric whose formula reads it, a
        finding whose SQL reads it, and a brief citing that finding — beside an ordinary table."""
        from aughor.ontology.context_graph import ContextGraph, GraphEdge, GraphNode, Provenance

        self._block_salaries(monkeypatch)
        cg = ContextGraph(org_id="o", connection_id="c1", schema_name="hr")

        def add(nid, kind, label, data):
            cg.add_node(GraphNode(id=nid, kind=kind, label=label, provenance=Provenance(source="glossary"),
                                  data=data))
        add("table:orders", "table", "orders", {"source_tables": ["orders"]})
        add("table:salaries", "table", "salaries", {"source_tables": ["salaries"]})
        add("metric:payroll", "metric", "payroll", {"tables": ["salaries"], "formula_sql": "SUM(amount)"})
        add("finding:f1", "finding", "Pay rose 9% for the top band", {"tables": ["salaries"]})
        add("brief:c1", "brief", "Pay review", {})
        for frm, kind, to in (("metric:payroll", "derived_from", "table:salaries"),
                              ("finding:f1", "grounded_in", "table:salaries"),
                              ("brief:c1", "derived_from", "finding:f1")):
            cg.add_edge(GraphEdge(id=f"{frm}-{kind}-{to}", kind=kind, from_id=frm, to_id=to,
                                  provenance=Provenance(source="glossary")))
        _patch_graph(monkeypatch, cg)
        return cg

    def test_search_withholds_every_node_that_rests_on_a_restricted_table_and_counts_them(self, monkeypatch):
        """The defect this door had: it trimmed table nodes only, so a metric, a finding and a brief over the
        restricted table reached an outside agent with their text. Each is withheld, and the count is said."""
        cg = self._over_salaries(monkeypatch)
        monkeypatch.setattr("aughor.ontology.context_graph_search.search_graph",
                            lambda g, q, top_k=10: [(n, 1.0) for n in cg.nodes.values()])
        out = search_graph("c1", "pay")
        assert [n["id"] for n in out["nodes"]] == ["table:orders"]
        assert out["count"] == 1 and "[4 items withheld by data governance" in out["notice"]
        assert "salar" not in out["notice"].lower() and "pay" not in out["notice"].lower()

    def test_the_trim_reads_the_graphs_own_schema_when_the_caller_names_none(self, monkeypatch):
        """No caller of the door passes a schema, and a securable names the table under its schema — so the trim
        looked up a securable with an empty schema and never matched a tag."""
        cg = self._over_salaries(monkeypatch)
        asked: list[str] = []
        from aughor.govern import tags as T
        blocked = T.check
        monkeypatch.setattr(T, "check", lambda s, held, bypass=False: (asked.append(s), blocked(s, held))[1])
        monkeypatch.setattr("aughor.ontology.context_graph_search.search_graph",
                            lambda g, q, top_k=10: [(cg.nodes["table:salaries"], 1.0)])
        assert search_graph("c1", "salaries")["nodes"] == []
        assert asked == ["table:c1.hr.salaries"]

    def test_describe_leaves_out_a_related_node_over_a_restricted_table_and_says_so(self, monkeypatch):
        """The edge sweep on this door: an edge names its far end, so a related finding over a restricted table
        handed its id to the agent beside the table it was asked about."""
        cg = self._over_salaries(monkeypatch)
        cg.add_edge(cg.edges["finding:f1-grounded_in-table:salaries"].model_copy(
            update={"id": "finding:f1-grounded_in-table:orders", "to_id": "table:orders"}))
        out = describe_entity("c1", "orders")
        assert out["available"] is True and out["related"] == []
        assert "withheld by data governance" in out["notice"]

    def test_nothing_tagged_trims_nothing(self, monkeypatch):
        cg = self._over_salaries(monkeypatch)
        from aughor.govern import tags as T
        from aughor.govern.tags import ClearanceDecision
        monkeypatch.setattr(T, "check", lambda s, held, bypass=False: ClearanceDecision(securable=s, allowed=True))
        monkeypatch.setattr("aughor.ontology.context_graph_search.search_graph",
                            lambda g, q, top_k=10: [(n, 1.0) for n in cg.nodes.values()])
        out = search_graph("c1", "pay")
        assert len(out["nodes"]) == 5 and out["notice"] == ""


# ── table health ────────────────────────────────────────────────────────────────────

def test_no_checks_run_is_not_the_same_as_healthy():
    """An agent reads a bare 'healthy' as a fact and repeats it confidently."""
    out = get_table_health("c1", "orders")
    assert out["available"] is True and out["checked"] is False
    assert "No quality checks have run" in out["summary"]
    assert "healthy" not in out["summary"].lower()


def test_failing_checks_are_counted_and_summarised():
    from aughor.quality.results import Result, record

    record(Result(connection_id="c1", table_name="orders", rule_name="not_null",
                  passed=False, violations=4, criticality="error"))
    record(Result(connection_id="c1", table_name="orders", rule_name="fresh", passed=True))
    out = get_table_health("c1", "orders")
    assert out["checked"] and out["failing"] == 1 and out["blocking"] == 1
    assert "1 of 2 checks failing" in out["summary"]


def test_each_verdict_carries_its_staleness():
    """A verdict computed against yesterday's data is not authoritative today, and an
    agent has no way to know unless told."""
    from aughor.quality.results import Result, record

    record(Result(connection_id="c1", table_name="orders", rule_name="r", passed=True))
    out = get_table_health("c1", "orders")
    assert out["results"][0]["staleness"] in ("fresh", "stale", "unknown")


def test_health_without_a_table_asks_for_one():
    assert get_table_health("c1", "")["available"] is False


def test_an_unavailable_health_store_degrades(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr("aughor.quality.results.latest_for_tables", _boom)
    assert get_table_health("c1", "orders")["available"] is False


# ── trusted queries ─────────────────────────────────────────────────────────────────

def test_the_warrant_is_returned_not_a_flat_trusted_flag(monkeypatch):
    """A human-pinned answer and a consistency-promoted one are different claims. N1 built
    that distinction; flattening it at the boundary would throw it away where it matters
    most."""
    rows = [SimpleNamespace(question="q1", sql="SELECT 1", tags=["human_pinned"]),
            SimpleNamespace(question="q2", sql="SELECT 2", tags=["eval"]),
            SimpleNamespace(question="q3", sql="SELECT 3", tags=[])]
    monkeypatch.setattr("aughor.semantic.trusted_queries.list_trusted", lambda c: rows)
    out = list_trusted_queries("c1")
    assert [q["warrant"] for q in out["queries"]] == [
        "human_pinned", "eval_promoted", "recorded"]


def test_trusted_queries_degrade_rather_than_raise(monkeypatch):
    def _boom(_c):
        raise RuntimeError("store down")

    monkeypatch.setattr("aughor.semantic.trusted_queries.list_trusted", _boom)
    assert list_trusted_queries("c1")["available"] is False


# ── registration ────────────────────────────────────────────────────────────────────

def test_all_four_tools_are_registered_on_the_server():
    import inspect

    from aughor.mcp import server

    src = inspect.getsource(server)
    for tool in ("search_graph", "describe_entity", "get_table_health",
                 "list_trusted_queries"):
        assert f"async def {tool}(" in src, f"{tool} is not exposed as an MCP tool"


def test_every_table_deriving_tool_goes_through_the_trim():
    """The gate the scoping doc pinned: an external surface that skips the trim is the
    hole in the wall G5 built."""
    import inspect

    import aughor.mcp.knowledge_tools as KT

    for fn in (KT.search_graph, KT.describe_entity):
        assert "_trim_nodes" in inspect.getsource(fn)
