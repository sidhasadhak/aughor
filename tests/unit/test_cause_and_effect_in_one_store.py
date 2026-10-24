"""Cause and effect in one store (Arc ED, ED-5; ROADMAP §3.58 — the user, 2026-10-24: *"Impacts are the one store"*).

What one promise does to another had two stores: the ontology's declared impacts (``ontology/impacts.py``), declared by
a person and measured through the object door, and a file of causes the model proposed at the end of an analysis
(``lifecycle/causal.py``), promoted on an outcome. Measured on the live install the same day: 222 proposals from 101
investigations, 175 of them filed under the connection id "workspace", and no confirmed edge ever written — and the
alert summary's reader of that file raised on every call (it asked a list for ``.get("edges")``), so its section never
appeared.

With ``ontology.impacts_only`` on, the files are neither read nor written, the model is not asked for causes, and the
alert summary words the declared impacts by their mechanism. The falsifier (§3.58): an alert summary names a cause the
impacts store does not hold.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aughor.agent import prompts_investigate as P
from aughor.kernel.flags import flag_overrides
from aughor.lifecycle import causal as CG
from aughor.monitors import alert_summary as AS
from aughor.ontology.impacts import impact_words
from aughor.ontology.models import Impact, OntologyGraph

ON = {"ontology.impacts_only": True}
OFF = {"ontology.impacts_only": False}
CONN = "conn-ed5"
EDGE = {"id": "e1", "from_signal": "a sizing chart change", "to_signal": "returns rose", "weight": 3,
        "confirmed_by": ["inv-1"], "conn_id": CONN}
PROPOSAL = {"from_signal": "a sizing chart change", "to_signal": "returns rose", "confidence": 0.7,
            "inv_id": "inv-1", "conn_id": CONN}


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A confirmed edge and a proposal on disk, where the module reads them."""
    graph, proposals = tmp_path / "causal_graph.json", tmp_path / "causal_proposals.json"
    graph.write_text(json.dumps([EDGE]))
    proposals.write_text(json.dumps({"inv-1": [PROPOSAL]}))
    monkeypatch.setenv("AUGHOR_CAUSAL_GRAPH_FILE", str(graph))
    monkeypatch.setenv("AUGHOR_CAUSAL_PROPOSALS_FILE", str(proposals))
    return graph, proposals


def _impact(iid: str, mechanism: str = "influence", verified=True, broke=0.42, kept=0.18, **more) -> Impact:
    return Impact(id=iid, display_name=iid.replace("_", " ").capitalize(), upstream=f"fulfilment.{iid}_up",
                  downstream="fulfilment.delivery", mechanism=mechanism, verified=verified, rate_when_broke=broke,
                  rate_when_kept=kept, upstream_broke=120, upstream_kept=880, lead="order", **more)


def _graph(*impacts: Impact) -> OntologyGraph:
    return OntologyGraph(connection_id=CONN, schema_fingerprint="ed5", impacts={i.id: i for i in impacts})


@pytest.fixture
def declared(monkeypatch):
    """The connection's stored ontology, with an influence, a validated impact, a formula and one that does not hold."""
    graph = _graph(_impact("late_dispatch"), _impact("short_pick", broke=0.61, kept=0.12),
                   _impact("refund_lag", mechanism="validated", evidence="the decision to pre-pack, reviewed better"),
                   _impact("same_day", mechanism="formula", verified=None, formula="delivery = dispatch + transit"),
                   _impact("weekend_orders", verified=False, broke=0.2, kept=0.21))
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: graph)
    return graph


# ── the files ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_on_the_proposed_causes_are_neither_read_nor_written(files):
    graph_file, proposals_file = files
    before = (graph_file.read_bytes(), proposals_file.read_bytes())
    with flag_overrides(ON):
        assert CG.load_causal_graph(CONN) == [] and CG.load_proposals("inv-1") == []
        assert CG.build_causal_context_section("returns rose", conn_id=CONN) == ""
        CG.save_proposals("inv-2", [CG.CausalProposal(**{**PROPOSAL, "inv_id": "inv-2"})])
        assert CG.promote_on_outcome("inv-1") == 0
        told = CG.promote_on_record_outcome("inv-1", "better")
        assert told["affected"] == 0 and told["did"].startswith("nothing: what one promise does to another")
    assert (graph_file.read_bytes(), proposals_file.read_bytes()) == before   # untouched, and not deleted


def test_off_the_proposed_causes_are_read_and_written_as_before(files):
    graph_file, proposals_file = files
    with flag_overrides(OFF):
        assert [e.to_signal for e in CG.load_causal_graph(CONN)] == ["returns rose"]
        assert "a sizing chart change → returns rose (confirmed 3×)" in CG.build_causal_context_section("returns rose", CONN)
        CG.save_proposals("inv-2", [CG.CausalProposal(**{**PROPOSAL, "inv_id": "inv-2"})])
        assert "inv-2" in json.loads(proposals_file.read_text())
        assert CG.promote_on_outcome("inv-1") == 1
        written = json.loads(graph_file.read_text())
        assert len(written) == 2 and written[1]["confirmed_by"] == ["inv-1"]   # the proposal promoted, by its own id


# ── the falsifier: the alert summary ─────────────────────────────────────────────────────────────────────────────

def test_an_alert_summary_names_only_the_impacts_the_store_holds(files, declared):
    with flag_overrides(ON):
        summary = AS.build_alert_summary(CONN)
    kinds = [s.kind for s in summary.sections]
    assert "causal_links" not in kinds and kinds.count("impacts") == 1
    section = next(s for s in summary.sections if s.kind == "impacts")
    imp = declared.impacts
    assert section.title == "Impacts"
    assert section.items == [
        impact_words(declared, imp["refund_lag"]),                # validated first
        impact_words(declared, imp["short_pick"]),                # then influences, the widest difference first
        impact_words(declared, imp["late_dispatch"]),
        impact_words(declared, imp["same_day"]),                  # then what is exact by definition
        "1 declared impact not measured to hold: Weekend orders",  # said, not left out
    ]
    assert "returns rose" not in summary.to_markdown()            # the file's edge is named nowhere


def test_a_summary_says_how_many_more_hold_and_has_no_section_when_none_is_declared(monkeypatch):
    many = _graph(*(_impact(f"up_{n}", broke=0.5 + n / 100) for n in range(7)))
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: many)
    with flag_overrides(ON):
        section = AS.impacts_section(CONN)
    assert len(section.items) == AS.MAX_IMPACTS + 1
    assert section.items[-1] == "2 more declared impacts hold; the ontology's processes list every one"
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: _graph())
    assert AS.impacts_section(CONN) is None
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: None)
    assert AS.impacts_section(CONN) is None


def test_off_the_alert_summary_reads_no_impacts(declared):
    with flag_overrides(OFF):
        summary = AS.build_alert_summary(CONN)
    assert "impacts" not in [s.kind for s in summary.sections]


def test_an_impact_line_is_judged_on_its_own_at_departure_not_held_as_a_cause(monkeypatch):
    from aughor.briefing import delivery
    seen = []
    monkeypatch.setattr("aughor.govern.departure.line_holds",
                        lambda line, conn_id, declared=False: seen.append(line) or ([] if "kept" in line else ["no"]))
    brief = AS.AlertSummary(conn_id=CONN, period="week", generated_at="2026-10-24T00:00:00Z", sections=[
        AS.AlertSummarySection(title="Impacts", kind="impacts", items=["where it was kept: 18%", "a bare 42%"])])
    out, reasons = delivery.hold_lines(brief, CONN)
    assert seen == ["where it was kept: 18%", "a bare 42%"]
    assert out.sections[0].items == ["where it was kept: 18%"] and len(reasons) == 1


# ── an analysis is not asked for causes ──────────────────────────────────────────────────────────────────────────

def test_on_an_analysis_is_not_asked_for_causes_and_its_answer_widens_as_before():
    assert P.CAUSAL_LINKS_RULE in P.SYNTHESIS_CORE_RULES          # the rule removed is the rule the prompt carries
    with flag_overrides(ON):
        for waterfall in (True, False):
            asked = P.synthesis_ask_model(waterfall)
            assert "causal_links" not in asked.model_fields
            assert ("attribution_waterfall" in asked.model_fields) is waterfall
            assert P.CAUSAL_LINKS_RULE not in P.synthesis_system_prompt(waterfall)
            fields = {n: f for n, f in asked.model_fields.items()}
            answer = asked(**{"headline": "h", "executive_summary": "e", "total_change_label": "t",
                              "confidence": "LOW", "confidence_justification": "j", "recommendations": [],
                              **({"attribution_waterfall": []} if "attribution_waterfall" in fields else {})})
            wide = P.widen_synthesis(answer)
            assert isinstance(wide, P.ADASynthesisModel) and wide.causal_links == []


def test_off_the_analysis_is_asked_exactly_as_before():
    with flag_overrides(OFF):
        assert P.synthesis_ask_model(True) is P.ADASynthesisModel and P.synthesis_ask_model(False) is P.SynthesisAsk
        assert P.CAUSAL_LINKS_RULE in P.synthesis_system_prompt(True)


# ── the door that served the file ────────────────────────────────────────────────────────────────────────────────

def test_the_causal_graph_door_says_where_the_answer_moved(files):
    from aughor.api import app
    client = TestClient(app)
    with flag_overrides(ON):
        r = client.get(f"/connections/{CONN}/causal-graph")
        assert r.status_code == 410 and "GET /ontology/processes" in r.json()["detail"]
    with flag_overrides(OFF):
        r = client.get(f"/connections/{CONN}/causal-graph")
        assert r.status_code == 200 and [e["to_signal"] for e in r.json()] == ["returns rose"]
