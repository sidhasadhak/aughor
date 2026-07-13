"""Rec 5 — the grounding-context receipt (flag ask.context_receipt).

Covers build_grounding_context() (the pure assembler), its GroundingContext
JSON/markdown shape, the byte-identical parity between the shared block producers
and the answer path's originals (no drift), and the GET /ask/context endpoint's
flag gating.
"""
from __future__ import annotations

from aughor.agent import grounding as G


# ── the pure assembler ────────────────────────────────────────────────────────

def test_all_blocks_present_in_order():
    ctx = G.build_grounding_context("why is revenue down", "samples")
    keys = [b.key for b in ctx.blocks]
    # prepends first, then schema-dependent, then the enrichment body
    assert keys[:4] == ["dialect_rules", "agent_brief", "trusted", "corrections"]
    assert "governed_metrics" in keys and "schema_slice" in keys and "glossary" in keys


def test_schema_dependent_blocks_skip_without_schema():
    ctx = G.build_grounding_context("q", "samples")  # no schema passed
    by_key = {b.key: b for b in ctx.blocks}
    assert by_key["schema_slice"].content == ""
    assert by_key["governed_metrics"].content == ""
    # still emitted as (empty) blocks so the receipt shows they were considered
    assert by_key["schema_slice"].present is False


def test_to_dict_and_markdown_shape():
    ctx = G.build_grounding_context("q", "samples")
    d = ctx.to_dict()
    assert d["question"] == "q" and d["connection_id"] == "samples"
    assert d["present_count"] == len(ctx.present)
    assert all({"key", "title", "present", "content"} <= set(b) for b in d["blocks"])
    md = ctx.to_markdown()
    assert md.startswith("# Grounding for")


# ── no-drift: shared producers == the answer path's originals ──────────────────

def test_dialect_rules_block_matches_original():
    from aughor.rules import get_chat_rules_block
    assert G.dialect_rules_block() == (get_chat_rules_block() or "")


def test_agent_brief_matches_original():
    from aughor.user_agents.context import agent_brief_block
    assert G.agent_brief() == (agent_brief_block() or "")


def test_correction_priors_matches_original():
    from aughor.verify.priors import build_corrections_section
    q, c = "why is refund rate high", "samples"
    assert G.correction_priors(q, c) == (build_corrections_section(q, c) or "")


def test_governed_metrics_matches_inline_assembly():
    # Byte-parity with the quick /ask path's former inline metrics_section
    # (unified bindings + grain block + feasibility gap), so the convergence into
    # _stream_chat cannot change the answer prompt.
    from aughor.db.connection import open_connection_for
    from aughor.semantic.canonical import unified_metric_grounding
    from aughor.semantic.data_understanding import build_data_understanding
    from aughor.semantic.metric_feasibility import unsupported_metric_gap
    db = open_connection_for("samples")
    schema = db.get_schema()
    q, c = "why is revenue down by channel", "samples"
    eff = getattr(db, "_schema_name", None)
    _mb = unified_metric_grounding(c, eff, schema_text=schema, question=q)
    expected = (_mb + "\n\n") if _mb else ""
    _gb = build_data_understanding(db, connection_id=c, schema=schema).grain_block
    if _gb:
        expected += _gb + "\n\n"
    _fg = unsupported_metric_gap(q, schema)
    if _fg:
        expected += "DATA AVAILABILITY — " + _fg + ".\n\n"
    assert G.governed_metrics(q, c, db=db, schema=schema, eff_schema=eff) == expected


def test_schema_slice_matches_inline_link():
    from aughor.db.connection import open_connection_for
    from aughor.tools.schema_linker import link_schema_for_prompt
    db = open_connection_for("samples")
    schema = db.get_schema()
    q, c = "why is revenue down by channel", "samples"
    expected = link_schema_for_prompt(q, schema, top_k_tables=8, top_k_cols=8, connection_id=c)
    assert G.schema_slice(q, c, schema=schema) == expected


def test_schema_slice_falls_back_to_full_schema_on_failure(monkeypatch):
    import aughor.tools.schema_linker as sl
    monkeypatch.setattr(sl, "link_schema_for_prompt",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert G.schema_slice("q", "samples", schema="FULL SCHEMA TEXT") == "FULL SCHEMA TEXT"


def test_governed_metrics_without_db_is_unified_only():
    # The endpoint passes db (rich receipt); a db-less caller gets just the bindings.
    from aughor.db.connection import open_connection_for
    from aughor.semantic.canonical import unified_metric_grounding
    db = open_connection_for("samples")
    schema = db.get_schema()
    q, c = "why is revenue down by channel", "samples"
    eff = getattr(db, "_schema_name", None)
    _mb = unified_metric_grounding(c, eff, schema_text=schema, question=q)
    assert G.governed_metrics(q, c, schema=schema, eff_schema=eff) == ((_mb + "\n\n") if _mb else "")


def test_producers_degrade_to_empty_not_raise(monkeypatch):
    # A failing producer must yield "" (never break the answer/receipt).
    import aughor.semantic.kb_retriever as kb
    monkeypatch.setattr(kb, "retrieve_for_planning", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert G.kb_patterns("q", "samples") == ""


# ── endpoint gating ───────────────────────────────────────────────────────────

def test_endpoint_404_when_flag_off(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_CONTEXT_RECEIPT", "0")
    r = client.get("/ask/context", params={"connection": "samples", "question": "why is revenue down"})
    assert r.status_code == 404


def test_endpoint_returns_receipt_when_flag_on(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_CONTEXT_RECEIPT", "1")
    r = client.get("/ask/context", params={"connection": "samples", "question": "why is revenue down"})
    assert r.status_code == 200
    body = r.json()
    assert "receipt" in body and "markdown" in body
    assert body["receipt"]["connection_id"] == "samples"
    keys = [b["key"] for b in body["receipt"]["blocks"]]
    assert "schema_slice" in keys and "dialect_rules" in keys
    # with a real connection schema resolved, the schema slice should populate
    by_key = {b["key"]: b for b in body["receipt"]["blocks"]}
    assert by_key["schema_slice"]["present"] is True


def test_endpoint_unknown_connection_404(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_CONTEXT_RECEIPT", "1")
    r = client.get("/ask/context", params={"connection": "nope-not-real", "question": "q"})
    assert r.status_code == 404
