"""Custom instructions are CONSUMED, not just stored.

Sprint 53 shipped GET/PUT ``/connections/{id}/instructions`` and
``/canvases/{id}/instructions`` plus the Canvas Configure panel's Instructions
tab — and for fifteen months no generation path read either store: a user could
type "fiscal year starts in February" into a live editor and every answer
ignored it (the features-stall-at-TESTED-not-LEVERAGED class). These tests pin
the whole chain: the endpoints write the store the ``instructions`` grounding
block reads, the block lands in the assembled grounding context (the receipt IS
the prompt's blocks — one producer, no drift), and the quick-answer path
prepends it.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.agent import grounding as G
from aughor.semantic import instructions as I


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point both instruction stores at this test's own temp files (paths are
    resolved per call, so setenv wins without a module reload)."""
    monkeypatch.setenv("AUGHOR_INSTRUCTIONS_FILE", str(tmp_path / "instructions.json"))
    monkeypatch.setenv("AUGHOR_CANVAS_INSTRUCTIONS_FILE", str(tmp_path / "canvas_instructions.json"))
    return tmp_path


# ── the block itself ──────────────────────────────────────────────────────────

def test_nothing_stored_means_an_empty_block(stores):
    """The byte-identical guarantee: a scope with no instructions must add nothing."""
    assert I.build_instructions_block("conn_a", "cv_1") == ""


def test_connection_text_alone_renders(stores):
    I.set_connection_instructions("conn_a", "Fiscal year starts in February.")
    block = I.build_instructions_block("conn_a")
    assert "CUSTOM INSTRUCTIONS" in block
    assert "Fiscal year starts in February." in block
    assert "For this Canvas" not in block


def test_canvas_text_joins_only_under_its_own_canvas_scope(stores):
    I.set_canvas_instructions("cv_1", "Exclude test accounts.")
    assert "Exclude test accounts." in I.build_instructions_block("conn_a", "cv_1")
    # no canvas scope, or a sibling canvas → that canvas's rules stay out
    assert I.build_instructions_block("conn_a") == ""
    assert I.build_instructions_block("conn_a", "cv_2") == ""


def test_canvas_text_is_labelled_as_the_narrower_scope(stores):
    """Sprint 53 split the stores so two Canvases on one connection keep distinct
    business rules — the render must say which level a rule came from."""
    I.set_connection_instructions("conn_a", "Revenue means net_revenue.")
    I.set_canvas_instructions("cv_1", "Revenue here means gross_revenue.")
    block = I.build_instructions_block("conn_a", "cv_1")
    assert block.index("net_revenue") < block.index("takes precedence")
    assert block.index("takes precedence") < block.index("gross_revenue")


# ── the grounding context (the receipt == the prompt's blocks) ────────────────

def test_instructions_land_in_the_assembled_grounding_context(stores):
    I.set_connection_instructions("conn_a", "Fiscal year starts in February.")
    I.set_canvas_instructions("cv_1", "Exclude test accounts.")
    ctx = G.build_grounding_context("why is revenue down", "conn_a", canvas_id="cv_1")
    by_key = {b.key: b for b in ctx.blocks}
    assert by_key["instructions"].present
    assert "Fiscal year starts in February." in by_key["instructions"].content
    assert "Exclude test accounts." in by_key["instructions"].content


def test_block_absent_from_the_context_when_nothing_stored(stores):
    ctx = G.build_grounding_context("q", "conn_a", canvas_id="cv_1")
    by_key = {b.key: b for b in ctx.blocks}
    assert by_key["instructions"].present is False


# ── the endpoints write the store the prompt reads ────────────────────────────

def test_what_the_endpoints_store_is_what_the_prompt_gets(stores):
    """End to end through the API: the text a user PUTs is the text the grounding
    producer injects — the endpoint existing is not the feature; this is."""
    from fastapi.testclient import TestClient
    from aughor.api import app
    client = TestClient(app)

    r = client.put("/connections/conn_a/instructions",
                   json={"text": "Fiscal year starts in February."})
    assert r.status_code == 200, r.text
    r = client.put("/canvases/cv_1/instructions", json={"text": "Exclude test accounts."})
    assert r.status_code == 200, r.text

    assert client.get("/connections/conn_a/instructions").json()["text"] == \
        "Fiscal year starts in February."
    assert client.get("/canvases/cv_1/instructions").json()["text"] == \
        "Exclude test accounts."

    block = G.custom_instructions("conn_a", "cv_1")
    assert "Fiscal year starts in February." in block
    assert "Exclude test accounts." in block


# ── the answer path consumes the producer ─────────────────────────────────────

def test_quick_answer_path_prepends_the_instructions_block():
    """Wiring guard (the schema-scope idiom): the gap this feature closes was a
    store nothing consumed, so pin the consumption site itself."""
    from aughor.routers.investigations import _answer_core
    src = inspect.getsource(_answer_core)
    assert "custom_instructions" in src
    assert "prompt = _instr_sec + prompt" in src


def test_receipt_endpoint_forwards_the_canvas_scope():
    """GET /ask/context must stay in sync: the same producer, fed the same canvas."""
    from aughor.routers import investigations as inv
    src = inspect.getsource(inv.ask_context_endpoint)
    assert "canvas_id=canvas" in src
