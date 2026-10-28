"""Cause and effect in one store (Arc ED, ED-5; ROADMAP §3.58 — the user, 2026-10-24: *"Impacts are the one store"*).

What one promise does to another had two stores: the ontology's declared impacts (``ontology/impacts.py``), declared by
a person and measured through the object door, and a file of causes the model proposed at the end of an analysis
(``lifecycle/causal.py``), promoted on an outcome. Measured on the live install the same day: 222 proposals from 101
investigations, 175 of them filed under the connection id "workspace", and no confirmed edge ever written — and the
alert summary's reader of that file raised on every call (it asked a list for ``.get("edges")``), so its section never
appeared.

Now (part of the platform since 2026-10-28, ``lifecycle/causal.py`` deleted) the files are neither read nor written —
left on disk as they were — the model is not asked for causes, and the alert summary words the declared impacts by
their mechanism. The falsifier (§3.58): an alert summary names a cause the impacts store does not hold.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aughor.agent import prompts_investigate as P
from aughor.monitors import alert_summary as AS
from aughor.ontology.impacts import impact_words
from aughor.ontology.models import Impact, OntologyGraph

CONN = "conn-ed5"
EDGE = {"id": "e1", "from_signal": "a sizing chart change", "to_signal": "returns rose", "weight": 3,
        "confirmed_by": ["inv-1"], "conn_id": CONN}
PROPOSAL = {"from_signal": "a sizing chart change", "to_signal": "returns rose", "confidence": 0.7,
            "inv_id": "inv-1", "conn_id": CONN}


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A confirmed edge and a proposal on disk, where the deleted module read them."""
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

def test_the_proposed_causes_have_no_reader_or_writer_left():
    import importlib.util
    assert importlib.util.find_spec("aughor.lifecycle.causal") is None
    import aughor.agent.grounding as G
    assert "causal" not in {key for key, *_ in G._BLOCKS}            # no prompt section reads the file


# ── the falsifier: the alert summary ─────────────────────────────────────────────────────────────────────────────

def test_an_alert_summary_names_only_the_impacts_the_store_holds(files, declared):
    graph_file, proposals_file = files
    before = (graph_file.read_bytes(), proposals_file.read_bytes())
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
    assert (graph_file.read_bytes(), proposals_file.read_bytes()) == before   # untouched, and not deleted


def test_a_summary_says_how_many_more_hold_and_has_no_section_when_none_is_declared(monkeypatch):
    many = _graph(*(_impact(f"up_{n}", broke=0.5 + n / 100) for n in range(7)))
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: many)
    section = AS.impacts_section(CONN)
    assert len(section.items) == AS.MAX_IMPACTS + 1
    assert section.items[-1] == "2 more declared impacts hold; the ontology's processes list every one"
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: _graph())
    assert AS.impacts_section(CONN) is None
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn_id, schema_name=None: None)
    assert AS.impacts_section(CONN) is None


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

def test_an_analysis_is_not_asked_for_causes_and_its_answer_widens_as_before():
    assert "causal_links" not in P.ADASynthesisModel.model_fields
    assert "causal_links" not in P.SYNTHESIS_CORE_RULES
    assert P.synthesis_ask_model(True) is P.ADASynthesisModel and P.synthesis_ask_model(False) is P.SynthesisAsk
    for waterfall in (True, False):
        asked = P.synthesis_ask_model(waterfall)
        assert "causal_links" not in asked.model_fields
        assert ("attribution_waterfall" in asked.model_fields) is waterfall
        assert "causal_links" not in P.synthesis_system_prompt(waterfall)
        fields = {n: f for n, f in asked.model_fields.items()}
        answer = asked(**{"headline": "h", "executive_summary": "e", "total_change_label": "t",
                          "confidence": "LOW", "confidence_justification": "j", "recommendations": [],
                          **({"attribution_waterfall": []} if "attribution_waterfall" in fields else {})})
        wide = P.widen_synthesis(answer)
        assert isinstance(wide, P.ADASynthesisModel) and wide.attribution_waterfall == []


# ── the door that served the file ────────────────────────────────────────────────────────────────────────────────

def test_the_causal_graph_door_says_where_the_answer_moved(files):
    from aughor.api import app
    client = TestClient(app)
    r = client.get(f"/connections/{CONN}/causal-graph")
    assert r.status_code == 410 and "GET /ontology/processes" in r.json()["detail"]
