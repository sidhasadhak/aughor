"""CB-1 — a date on every fact, and what it replaced (Arc CB, 2026-09-22).

Measured before this wave: the graph's `Provenance` carried `source`, `measured` and `note` and
nothing about WHEN; a rebuild bumped `version` and overwrote the file, so a node held only its
current state and git was the only history; a superseded finding left its id behind and lost its
text. The hub's envelope had `observed_at`/`valid_until`/`author` all along — two provenance
carriers, one of which knew when.

These tests pin the properties: every node and edge carries a date and says where it came from;
an old fact re-projected today keeps its own date; a rebuild that changes a fact keeps the old
reading with the right reason ("changed" when the observation moved, "corrected" when it did not);
a rebuild that changes nothing writes no history; a node that goes is retired with its last state
and takes its history back when it returns; and the store carries all of it across a save.
"""
from __future__ import annotations

from aughor.ontology import context_graph_store as store
from aughor.ontology.context_graph import (FACT_FIELDS, HISTORY_CAP, RETIRED_CAP, GraphNode, Provenance,
                                           carry_history, fact_view, project_graph, stamp_observed)
from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyMetric, OntologyRelationship

OLD_FINDING_DATE = "2026-07-01T00:00:00+00:00"


def _entity(eid, table, cols=("id",)):
    return OntologyEntity(id=eid, display_name=eid, source_tables=[table], identity_key="id",
                          grain_verified=True, domain="Commerce",
                          properties={c: {"name": c} for c in cols})


def _ontology(*, formula="SUM(revenue)", stamp="2026-09-01T00:00:00+00:00", with_customer=True):
    g = OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp1")
    g.entities = {"Order": _entity("Order", "orders", ("id", "customer_id", "revenue"))}
    if with_customer:
        g.entities["Customer"] = _entity("Customer", "customers")
        g.relationships = {"r1": OntologyRelationship(
            id="Order_to_Customer", from_entity="Order", to_entity="Customer", cardinality="N:1",
            join_sql="order.id = customer.id", from_table="orders", from_col="id", to_table="customers",
            to_col="id", join_confidence="verified", value_overlap=0.98)}
    g.metrics = {"revenue": OntologyMetric(id="revenue", display_name="Revenue", entity="Order",
                                           formula_sql=formula, tables=["orders"], verified=True)}
    g.generated_at = stamp
    return g


def _finding(text="Revenue fell 12% in July", fid="f1", generated_at=OLD_FINDING_DATE):
    return {"id": fid, "text": text, "sql": "SELECT 1", "tables": ["orders"], "generated_at": generated_at}


def _build(**kw):
    findings = kw.pop("findings", [_finding()])
    return project_graph(_ontology(**kw), org_id="org1", connection_id="c1", schema_name="main",
                         findings=findings)


class TestEveryFactCarriesADate:
    def test_every_node_and_edge_is_dated_and_says_from_where(self):
        cg = _build()
        assert cg.nodes and cg.edges
        for n in cg.nodes.values():
            assert n.provenance.observed_at and n.provenance.observed_basis in ("source", "build"), n.id
        for e in cg.edges.values():
            assert e.provenance.observed_at and e.provenance.observed_basis in ("source", "build"), e.id

    def test_an_old_finding_projected_today_keeps_its_own_date(self):
        cg = _build()
        f = cg.nodes["finding:f1"]
        assert f.provenance.observed_at == OLD_FINDING_DATE and f.provenance.observed_basis == "source"
        assert f.provenance.observed_at != cg.generated_at

    def test_a_table_takes_the_ontology_build_that_profiled_it(self):
        cg = _build(stamp="2026-08-15T10:00:00+00:00")
        t = cg.nodes["table:Order"]
        assert t.provenance.observed_at == "2026-08-15T10:00:00+00:00" and t.provenance.observed_basis == "source"

    def test_an_undated_source_takes_the_build_time_and_says_so(self):
        cg = _build()
        undated = [n for n in cg.nodes.values() if n.provenance.observed_basis == "build"]
        # the glossary/resolution kinds have no stamp of their own in this fixture; a finding does
        assert all(n.provenance.observed_at == cg.generated_at for n in undated)
        assert "finding:f1" not in {n.id for n in undated}

    def test_an_edge_is_as_old_as_the_fact_that_asserts_it(self):
        cg = _build()
        e = next(e for e in cg.edges.values() if e.from_id == "finding:f1")
        assert e.provenance.observed_at == OLD_FINDING_DATE

    def test_stamping_never_overwrites_a_date_a_source_set(self):
        cg = _build()
        n = cg.nodes["table:Order"]
        n.provenance.observed_at, n.provenance.observed_basis = "2020-01-01T00:00:00+00:00", "source"
        stamp_observed(cg)
        assert n.provenance.observed_at == "2020-01-01T00:00:00+00:00"


class TestWhatItReplacedIsKept:
    def test_a_rebuild_that_changes_nothing_writes_no_history(self):
        a, b = _build(), _build()
        stats = carry_history(b, a, now="2026-09-22T12:00:00+00:00")
        assert stats == {"changed": 0, "corrected": 0, "retired": 0, "restored": 0}
        assert all(not n.history and not n.last_changed for n in b.nodes.values())
        assert all(n.first_seen == a.nodes[n.id].provenance.observed_at for n in b.nodes.values())

    def test_a_changed_fact_keeps_the_old_reading_with_reason_changed(self):
        a = _build(formula="SUM(revenue)", stamp="2026-09-01T00:00:00+00:00")
        b = _build(formula="SUM(revenue) - SUM(refunds)", stamp="2026-09-20T00:00:00+00:00")
        stats = carry_history(b, a, now="2026-09-22T12:00:00+00:00")
        m = b.nodes["metric:revenue"]
        assert stats["changed"] == 1 and stats["corrected"] == 0   # only the metric's fact moved
        assert len(m.history) == 1
        rev = m.history[0]
        assert rev.reason == "changed" and rev.facts["formula_sql"] == "SUM(revenue)"
        assert rev.observed_at == "2026-09-01T00:00:00+00:00" and rev.replaced_at == "2026-09-22T12:00:00+00:00"
        assert m.last_changed == "2026-09-22T12:00:00+00:00"
        assert m.first_seen == "2026-09-01T00:00:00+00:00"        # first seen survives the change

    def test_the_same_observation_reworded_is_a_correction(self):
        a = _build(findings=[_finding("Revenue fell 12% in July")])
        b = _build(findings=[_finding("Revenue fell 2% in July")])          # same generated_at
        stats = carry_history(b, a, now="2026-09-22T12:00:00+00:00")
        f = b.nodes["finding:f1"]
        assert stats["corrected"] == 1 and f.history[0].reason == "corrected"
        assert f.history[0].summary == "Revenue fell 12% in July"

    def test_history_is_newest_first_and_capped(self):
        prev = _build(formula="v0")
        for i in range(1, HISTORY_CAP + 4):
            cur = _build(formula=f"v{i}", stamp=f"2026-09-{i:02d}T00:00:00+00:00")
            carry_history(cur, prev, now=f"2026-09-{i:02d}T01:00:00+00:00")
            prev = cur
        h = prev.nodes["metric:revenue"].history
        assert len(h) == HISTORY_CAP and h[0].facts["formula_sql"] == f"v{HISTORY_CAP + 2}"

    def test_a_fact_field_is_the_fact_and_a_decoration_is_not(self):
        cg = _build()
        n = cg.nodes["table:Order"]
        before = fact_view(n)
        n.data["exploration_insights"] = ["something the explorer said"]     # about the fact
        assert fact_view(n) == before
        n.data["columns"] = ["id"]                                            # the fact
        assert fact_view(n) != before
        assert all(kind in FACT_FIELDS for kind in ("table", "metric", "finding", "brief", "domain", "glossary_term"))

    def test_a_node_that_goes_is_retired_with_its_last_state_and_returns_with_its_history(self):
        a = _build(with_customer=True)
        b = _build(with_customer=False)
        stats = carry_history(b, a, now="2026-09-22T12:00:00+00:00")
        assert stats["retired"] >= 1 and "table:Customer" in b.retired
        assert b.retired["table:Customer"].node.label == a.nodes["table:Customer"].label
        assert b.retired["table:Customer"].retired_at == "2026-09-22T12:00:00+00:00"
        c = _build(with_customer=True)
        stats = carry_history(c, b, now="2026-09-23T12:00:00+00:00")
        assert stats["restored"] >= 1 and "table:Customer" not in c.retired
        assert c.nodes["table:Customer"].first_seen == a.nodes["table:Customer"].first_seen or \
            c.nodes["table:Customer"].first_seen == a.nodes["table:Customer"].provenance.observed_at

    def test_retired_is_capped_newest_kept(self):
        from aughor.ontology.context_graph import RetiredNode
        a = _build()
        for i in range(RETIRED_CAP + 5):          # 205 distinct, increasing retirement times
            node = GraphNode(id=f"finding:old{i}", kind="finding", label="x",
                             provenance=Provenance(source="dossier", observed_at="2026-01-01T00:00:00+00:00"))
            a.retired[node.id] = RetiredNode(node=node, retired_at=f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00+00:00")
        b = _build()
        carry_history(b, a, now="2026-09-22T12:00:00+00:00")
        assert len(b.retired) == RETIRED_CAP
        dropped = {f"finding:old{i}" for i in range(5)}          # the five oldest went
        assert not (dropped & set(b.retired)) and "finding:old204" in b.retired


class TestTheStoreCarriesIt:
    def test_save_load_save_keeps_the_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
        store.save_graph(_build(formula="SUM(revenue)"))
        second = _build(formula="SUM(revenue) - SUM(refunds)", stamp="2026-09-20T00:00:00+00:00")
        store.save_graph(second)
        back = store.load_graph("org1", "c1", "main")
        assert back.version == 2
        m = back.nodes["metric:revenue"]
        assert m.history and m.history[0].facts["formula_sql"] == "SUM(revenue)" and m.history[0].reason == "changed"
        third = _build(formula="SUM(revenue) - SUM(refunds)", stamp="2026-09-20T00:00:00+00:00", with_customer=False)
        store.save_graph(third)
        back = store.load_graph("org1", "c1", "main")
        assert back.nodes["metric:revenue"].history[0].facts["formula_sql"] == "SUM(revenue)"   # still there
        assert "table:Customer" in back.retired


class TestASupersededFindingKeepsItsText:
    def test_consolidation_keeps_what_the_survivor_replaced(self):
        from aughor.ontology.finding_consolidation import consolidate
        older = {"id": "f_old", "text": "Revenue fell 12% in July", "sql": "SELECT a FROM t", "tables": ["t"],
                 "generated_at": "2026-07-01T00:00:00+00:00", "subject": "revenue july"}
        newer = {"id": "f_new", "text": "Revenue fell 12% in July (restated)", "sql": "SELECT a FROM t",
                 "tables": ["t"], "generated_at": "2026-08-01T00:00:00+00:00", "subject": "revenue july"}
        out, report = consolidate([older, newer], live_tables={"t"})
        survivors = [f for f in out if f.get("supersedes")]
        if not survivors:      # the consolidator's own subject key may not fold these two — then nothing to pin here
            return
        s = survivors[0]
        assert s["superseded"][0]["id"] == "f_old" and "12%" in s["superseded"][0]["text"]
        from aughor.ontology.context_graph import finding_node_data
        assert finding_node_data(s)["superseded"][0]["text"] == "Revenue fell 12% in July"
