"""ON-10 — the quick answer frames the question too.

The deep investigation has read a frame since ON-10: each business term resolved against what the business DECLARED — a
promise, a lag, a rule — with the SQL the object door compiles for it. The quick answer did not, so "what share of lines
broke the dispatch promise" re-derived "late" from column names on one door and read the declared definition on the
other. The frame is now one grounding producer, given to the quick answer and shown by the grounding receipt (the
receipt IS the prompt's blocks), with no model call: an ambiguous frame lists every definition the words fit.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from aughor.agent import grounding as G
from aughor.ontology import overrides as OV
from aughor.ontology import store as ST
from aughor.ontology.models import OntologyGraph
from aughor.util.json_store import KeyedJsonStore

REPO = Path(__file__).resolve().parents[2]
CONN = "frame-quick-t"
DISPATCH = "What percentage of order lines broke the dispatch promise?"


@pytest.fixture(autouse=True)
def served(tmp_path, monkeypatch):
    """Olist's declared business ontology — its order-to-delivery process and rules, measured — served for one scope."""
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    graph = OntologyGraph.model_validate(json.loads((REPO / "evals" / "ablation_olist_business_ontology.json").read_text()))
    ST.save_ontology(CONN, "ecommerce", "fp", graph.model_copy(update={"connection_id": CONN, "schema_name": "ecommerce"}))


def test_a_question_that_reaches_a_declared_definition_is_framed_for_the_quick_answer():
    block = G.question_frame(DISPATCH, CONN, schema_name="ecommerce")
    assert block.startswith("QUESTION FRAME") and "dispatch_breach_rate, compiled by the object door" in block
    assert block.endswith("\n\n")
    assert G.question_frame("How many sellers are there in each state?", CONN, schema_name="ecommerce") == ""


def test_an_ambiguous_question_lists_every_definition_it_fits_and_asks_no_model(monkeypatch):
    import aughor.agent.framing as AF

    def no_model(*_args, **_kwargs):
        raise AssertionError("the quick answer asked a model to choose a definition")
    monkeypatch.setattr(AF, "choose_definition", no_model)
    block = G.question_frame("What was late last month?", CONN, schema_name="ecommerce")
    assert "fit 2 declared definitions" in block
    assert "dispatch_breach_rate" in block and "delivery_breach_rate" in block


def test_the_grounding_receipt_carries_the_frame_the_answer_is_given():
    ctx = G.build_grounding_context(DISPATCH, CONN, eff_schema="ecommerce")
    frame = {b.key: b for b in ctx.blocks}["question_frame"]
    assert frame.present and frame.content == G.question_frame(DISPATCH, CONN, schema_name="ecommerce")
    empty = G.build_grounding_context("How many sellers are there in each state?", CONN, eff_schema="ecommerce")
    assert {b.key: b for b in empty.blocks}["question_frame"].present is False


def test_the_quick_answer_path_prepends_the_frame():
    """Wiring guard, the instructions block's idiom: a producer nothing consumes is the gap this closes."""
    from aughor.routers.investigations import _answer_core
    src = inspect.getsource(_answer_core)
    assert "_grounding_frame(question, connection_id" in src and "prompt = _frame_sec + prompt" in src


def test_the_frame_compiles_in_the_dialect_the_writer_writes():
    class Native:
        dialect, writes_native_sql = "bigquery", True

    class Translating:
        dialect, writes_native_sql = "postgres", False
    assert (G.writer_dialect(Native()), G.writer_dialect(Translating()), G.writer_dialect(None)) == (
        "bigquery", "duckdb", "duckdb")
