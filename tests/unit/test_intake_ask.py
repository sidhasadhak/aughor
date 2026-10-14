"""P2 of the canvas-output study (2026-10-14): the intake on the PE-2 diet.

The long intake prompt is 12.9k chars of case law — ten "(critical)" guards, thirteen "NEVER"s, four
references to a PROFILE block that is empty on the analyst path — and nearly every guard has a
verifier that runs after the model answers (the metric-table, dimension and window validators with
their one correction retry; the date-column resolver; the coverage clamp; the routers; the metric
pin). A capable binding now reads the ask; a baseline one keeps the long form, the way the narrator's
diet is tiered. Hermetic: the intake model is a stub that records its prompt."""
from __future__ import annotations

import re
from types import SimpleNamespace as NS

import pytest

import aughor.agent.investigate as I
from aughor.agent.prompts_investigate import INTAKE_ASK, INTAKE_PROMPT, IntakeOutput, intake_prompt

KW = dict(question="q", schema="TABLE: orders\n  id INT", scan_context="", scan_section="", sql_context="ENGINE: duckdb",
          events_section="", origin_finding_section="")


def test_the_ask_is_a_fraction_of_the_long_form_and_carries_no_case_law():
    assert intake_prompt(True) is INTAKE_ASK and intake_prompt(False) is INTAKE_PROMPT
    assert len(INTAKE_ASK) < len(INTAKE_PROMPT) / 3
    assert "critical" not in INTAKE_ASK.lower() and "NEVER" not in INTAKE_ASK and "MUST" not in INTAKE_ASK
    assert "PROFILE" not in INTAKE_ASK                      # the block is a section only when there is one
    assert INTAKE_PROMPT.count("PROFILE") == 4              # the long form still tells a model to read it


def test_both_registers_take_the_same_fields():
    long, ask = INTAKE_PROMPT.format(**KW), INTAKE_ASK.format(**KW)
    assert "QUESTION: q" in long and "QUESTION: q" in ask and "ENGINE: duckdb" in ask


def test_the_ask_keeps_every_judgment_only_the_model_can_make():
    for phrase in ("CANONICAL METRIC", "Losing money", "0/1 flag", "relationship_left_sql",
                   "intervention_column", "comparison_segment_sql", "up to 8", "intake_notes"):
        assert phrase in INTAKE_ASK, phrase


class _Intake:
    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, **kw):
        self.prompts.append(kw.get("user", ""))
        return IntakeOutput(metric_label="revenue", metric_sql="SUM(sale_price)", observation_start="", observation_end="",
                            observation_label="", comparison_start="", comparison_end="", comparison_label="",
                            date_column="orders.created_at", metric_table="orders", dimensions=["orders.status"],
                            intake_notes="", cross_sectional=False)


SCHEMA = "TABLE: orders\n  id VARCHAR\n  created_at TIMESTAMP\n  sale_price DOUBLE\n  status VARCHAR\n"


@pytest.fixture
def intake(monkeypatch):
    model = _Intake()
    monkeypatch.setattr(I, "_provider", lambda role: model)
    import aughor.agent.explore as ex
    import aughor.semantic.data_understanding as du
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")
    monkeypatch.setattr(du, "build_data_understanding", lambda *a, **k: NS(grounding_block=lambda: "", trusted_used=[]))
    monkeypatch.setattr(I, "_measure_date_span", lambda *a, **k: ("", ""))
    import aughor.agent.framing as AF
    monkeypatch.setattr(AF, "frame_from_state", lambda state, dialect="duckdb", provider=None: None)
    return model


def _run(model, capable: bool, monkeypatch, scan: str = ""):
    import aughor.llm.profile as P
    monkeypatch.setattr(P, "profile_for", lambda role: NS(capable=capable))
    state = {"question": "Which 10 categories brought in the most revenue in the last 6 months?",
             "schema_context": SCHEMA, "scan_context": scan, "connection_id": "", "scope_schema": ""}
    I.ada_intake(state, conn=object())
    return model.prompts[0]


def test_a_capable_binding_reads_the_ask_with_no_empty_profile_section(intake, monkeypatch):
    prompt = _run(intake, True, monkeypatch)
    assert "Fill the specification from the question and the schema." in prompt
    assert "PROFILE CONTEXT" not in prompt and "(critical)" not in prompt
    assert "QUESTION: Which 10 categories" in prompt and "TABLE: orders" in prompt


def test_a_capable_binding_still_sees_the_profile_when_there_is_one(intake, monkeypatch):
    prompt = _run(intake, True, monkeypatch, scan="DATA PORTRAIT: orders 125,080 rows, 2019-01-11 → 2026-10-18")
    assert "PROFILE CONTEXT (date ranges, row counts, key columns):\nDATA PORTRAIT: orders 125,080 rows" in prompt


def test_a_baseline_binding_keeps_the_long_form_byte_for_byte(intake, monkeypatch):
    prompt = _run(intake, False, monkeypatch)
    assert "TASK: Parse this question into a precise investigation specification." in prompt
    assert prompt.count("(critical)") == 6 and "PROFILE CONTEXT (date ranges, row counts, key columns):\n\n" in prompt


def test_the_ask_names_the_model_only_judgments_once_each():
    """One word, one concept: the ask states each rule once, where the long form repeated its
    guards across sections."""
    for phrase in ("verbatim", "cross_sectional", "intake_notes carries"):
        assert len(re.findall(re.escape(phrase), INTAKE_ASK)) == 1, phrase
