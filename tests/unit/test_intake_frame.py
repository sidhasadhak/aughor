"""ON-10 — the deep analysis's intake reads the question through its frame.

The deep analysis's intake frames the question against the declared ontology before the intake model parses it: the frame block
leads the intake prompt, rides the filtered schema every phase planner reads, the drivers the question names lead
the dimensions, the reading joins the displayed specification, and the frame is kept for the answer. A question that
reaches nothing declared leaves the intake exactly as it was — the prompt byte for byte. Hermetic: the intake model
is a stub that records its prompt, and the frame is framed over the served Olist graph.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aughor.agent.framing as AF
import aughor.agent.investigate as I
from aughor.agent.investigate import ada_intake as run_intake
from aughor.agent.prompts_investigate import IntakeOutput
from aughor.ontology.framing import frame_question
from aughor.ontology.models import OntologyGraph

REPO = Path(__file__).resolve().parents[2]
OLIST = OntologyGraph.model_validate(json.loads((REPO / "evals" / "ablation_olist_business_ontology.json").read_text()))
SCHEMA = ("TABLE: ecommerce.order_items\n  order_id VARCHAR\n  seller_id VARCHAR\n  product_id VARCHAR\n"
          "  shipping_limit_date TIMESTAMP\n  price DOUBLE\n"
          "TABLE: ecommerce.orders\n  order_id VARCHAR\n  customer_id VARCHAR\n  order_status VARCHAR\n"
          "  order_approved_at TIMESTAMP\n  order_delivered_carrier_date TIMESTAMP\n"
          "TABLE: ecommerce.sellers\n  seller_id VARCHAR\n  seller_state VARCHAR\n")


class _Intake:
    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, **kw):
        self.prompts.append(kw.get("user", ""))
        return IntakeOutput(
            metric_label="late dispatch rate", metric_sql="AVG(CASE WHEN 1=1 THEN 1 ELSE 0 END)",
            observation_start="2017-01-01", observation_end="2018-08-31", observation_label="2017–2018",
            comparison_start="", comparison_end="", comparison_label="", date_column="ecommerce.orders.order_approved_at",
            metric_table="ecommerce.order_items", dimensions=["ecommerce.order_items.product_id"], intake_notes="",
            cross_sectional=True)


class _Grounding:
    def grounding_block(self):
        return "GRAINS: order_items is one row per line"

    trusted_used: list = []


@pytest.fixture
def intake(monkeypatch):
    model = _Intake()
    monkeypatch.setattr(I, "_provider", lambda role: model)
    import aughor.agent.explore as ex
    import aughor.semantic.data_understanding as du
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")
    monkeypatch.setattr(du, "build_data_understanding", lambda *a, **k: _Grounding())
    monkeypatch.setattr(I, "_measure_date_span", lambda *a, **k: ("", ""))
    return model


def _run(monkeypatch, model, question: str, framed: bool):
    monkeypatch.setattr(AF, "frame_from_state",
                        lambda state, dialect="duckdb", provider=None:
                        frame_question(state["question"], OLIST) if framed else None)
    state = {"question": question, "schema_context": SCHEMA, "scan_context": "", "connection_id": "",
             "scope_schema": "ecommerce"}
    out = run_intake(state, conn=object())
    return out, model.prompts[-1]


def test_a_declared_definition_leads_the_intake_rides_every_phase_and_is_kept_for_the_answer(monkeypatch, intake):
    out, prompt = _run(monkeypatch, intake, "Which seller states have the worst dispatch record?", framed=True)
    spec = out["_ada_intake"]
    assert prompt.startswith("QUESTION FRAME") and "dispatch_breach_rate, compiled by the object door" in prompt
    frame = spec["ontology_frame"]
    assert frame["outcomes"][frame["chosen"]]["name"] == "dispatch_breach_rate"
    schema = spec["filtered_schema"]
    assert schema.index("TABLE: ecommerce.order_items") < schema.index("QUESTION FRAME")   # after the tables, as the
    assert schema.count("QUESTION FRAME") == 1                                            # relationship block rides
    assert spec["dimensions"][0] == "ecommerce.sellers.seller_state"
    assert "ecommerce.sellers.seller_state" in spec["named_dimensions"]
    assert not any("product_category_name" in d for d in spec["named_dimensions"])   # reachable, but not named
    rows = out["investigation_phases"][0]["findings"][0]["rows"]
    assert ["Read as", frame["reading"]] in rows and frame["reading"].startswith('Read "dispatch"')


def test_a_question_that_reaches_nothing_declared_leaves_the_intake_byte_identical(monkeypatch, intake):
    from aughor.agent.prompts_investigate import INTAKE_PROMPT
    question = "How many sellers are there in each state?"
    framed, framed_prompt = _run(monkeypatch, intake, question, framed=True)
    bare, bare_prompt = _run(monkeypatch, intake, question, framed=False)
    written = INTAKE_PROMPT.format(question=question, schema=SCHEMA, scan_context="", events_section="",
                                   origin_finding_section=I._render_origin_finding_section(None))
    assert framed_prompt == written and bare_prompt == written      # the prompt the intake wrote before ON-10
    assert "ontology_frame" not in framed["_ada_intake"]
    assert framed["_ada_intake"]["filtered_schema"] == bare["_ada_intake"]["filtered_schema"]
    assert not any(r[0] == "Read as" for r in framed["investigation_phases"][0]["findings"][0]["rows"])


def test_a_framing_failure_is_tolerated_and_the_intake_reads_the_question_as_written(monkeypatch, intake):
    def boom(*a, **k):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(AF, "frame_from_state", boom)
    out = run_intake({"question": "What is causing a delay in warehouse dispatch?", "schema_context": SCHEMA,
                        "scan_context": "", "connection_id": "", "scope_schema": "ecommerce"}, conn=object())
    assert "ontology_frame" not in out["_ada_intake"] and "QUESTION FRAME" not in intake.prompts[-1]
