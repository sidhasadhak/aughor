"""Agent-proposed context, governed by blast radius (ontology/agent_notes.py).

The WrenAI `enrich-context` frame applied to our sinks: the conversation may write back
what it LEARNED, but what applies directly vs. what waits for a person is decided by the
artifact's blast radius — a column note is local and additive (applies), a table-level
claim is read by every future session (stages) — and never by how confident the model
feels. Evidence is required; a human note is never overwritten.

Hermetic: both stores are pointed at tmp_path.
"""
from __future__ import annotations

import pytest

from aughor.ontology import agent_notes as AN
from aughor.ontology import recommendations as REC
from aughor.ontology.column_config import load_table_config, set_column_flags


@pytest.fixture(autouse=True)
def _stores(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_COLUMN_CONFIG_ROOT", str(tmp_path / "colcfg"))
    monkeypatch.setattr(REC, "_ROOT", tmp_path / "recs")


def _propose(**kw):
    base = dict(target="column", table="orders", column="amount",
                note="amounts are EUR cents, not euros",
                evidence="SELECT MAX(amount) FROM orders → 4812900; the user confirmed cents",
                confidence="high", session_id="s1")
    base.update(kw)
    return AN.propose_note("c1", "public", **base)


# ── the policy table ──────────────────────────────────────────────────────────

def test_high_confidence_column_note_with_evidence_applies_directly():
    out = _propose()
    assert out.ok and out.action == "applied"
    flags = load_table_config("c1", "public", "orders")["amount"]
    assert flags.source == "agent"
    assert "EUR cents" in flags.note
    assert "agent-observed" in flags.note, "provenance rides with the note"


def test_med_or_low_confidence_column_note_is_staged_not_applied():
    for conf in ("med", "low"):
        out = _propose(confidence=conf, column=f"col_{conf}")
        assert out.ok and out.action == "staged", out
        assert out.recommendation_id
        assert load_table_config("c1", "public", "orders").get(f"col_{conf}") is None


def test_table_level_claim_is_always_staged_even_at_high_confidence():
    out = _propose(target="table", column="", note="one row per order line, NOT per order")
    assert out.ok and out.action == "staged"
    rec = REC.get_recommendation("c1", "public", out.recommendation_id)
    assert rec.kind == "table_note" and rec.entity == "orders"
    assert "evidence" in rec.reason


def test_evidence_is_required():
    out = _propose(evidence="")
    assert not out.ok and out.action == "rejected"
    assert "evidence" in out.reason


def test_a_human_note_is_never_overwritten():
    set_column_flags("c1", "public", "orders", "amount", note="net of VAT — finance owns this")
    out = _propose(note="gross of VAT")
    assert out.ok and out.action == "staged", "disagreement with a person is staged, not applied"
    assert "HUMAN note" in out.reason
    assert load_table_config("c1", "public", "orders")["amount"].note == "net of VAT — finance owns this"


def test_repeated_proposals_merge_and_bump_support():
    a = _propose(target="table", column="", note="one row per order line")
    b = _propose(target="table", column="", note="one row per order line", session_id="s2")
    assert a.recommendation_id == b.recommendation_id
    rec = REC.get_recommendation("c1", "public", a.recommendation_id)
    assert rec.support == 2 and len(rec.evidence) == 2


def test_bad_inputs_are_rejected_as_values_not_raises():
    assert _propose(target="galaxy").action == "rejected"
    assert _propose(confidence="certain").action == "rejected"
    assert _propose(column="").action == "rejected"
    assert _propose(note="").action == "rejected"


# ── the human's side ──────────────────────────────────────────────────────────

def test_accepting_a_staged_column_note_makes_it_a_human_note():
    out = _propose(confidence="med")
    res = AN.accept_note("c1", "public", out.recommendation_id)
    assert res and res["accepted"] == out.recommendation_id
    flags = load_table_config("c1", "public", "orders")["amount"]
    assert flags.source == "human" and "EUR cents" in flags.note
    assert REC.get_recommendation("c1", "public", out.recommendation_id).status == "accepted"


def test_accept_note_ignores_non_note_recommendations():
    assert AN.accept_note("c1", "public", "does-not-exist") is None


# ── the tool surface ──────────────────────────────────────────────────────────

def test_the_tool_is_on_the_roster_and_bound_to_the_session():
    from aughor.agent import platform_tools as PT
    roster = {t.name: t for t in PT.platform_tools("c1", session_id="sess-9")}
    assert "propose_context_note" in roster
    desc = roster["propose_context_note"].description.lower()
    assert "evidence" in desc and "never overwrites" in desc
    for hedge in ("if helpful", "when useful", "consider "):
        assert hedge not in desc


def test_agent_notes_survive_a_defaults_refresh():
    # Before 2026-08-15 only source="human" was sticky — an agent note would have been
    # wiped by the next intelligence build.
    from aughor.ontology.column_config import ensure_column_configs
    _propose()
    # A real profiler-shaped refresh (the "table.column" key shape defaults_from_profiles
    # reads) whose default policy for `amount` DIFFERS from the stored entry — the
    # refresh must still leave the agent note alone.
    profiles = {"orders.amount": {"table": "orders", "column": "amount", "dtype": "DOUBLE",
                                  "semantic_type": "measure", "null_rate": 0.0}}
    effective = ensure_column_configs("c1", "public", profiles)
    stored = load_table_config("c1", "public", "orders")["amount"]
    assert stored.source == "agent" and "EUR cents" in stored.note
    assert effective[("orders", "amount")].source == "agent"


def test_a_staged_note_is_ripe_at_first_sighting():
    # A metric-gap recommendation must recur before it surfaces (a one-off model slip is
    # not a proposal); a note was staged deliberately with evidence and must be visible
    # to the reviewer immediately — otherwise `ripe_only` hides it and nobody ever accepts.
    out = _propose(target="table", column="", note="one row per order line")
    rec = REC.get_recommendation("c1", "public", out.recommendation_id)
    assert rec.support == 1 and rec.ripe
    metric = REC.OntologyRecommendation(id="m1", kind="metric", target_id="x", entity="orders", support=1)
    assert not metric.ripe
