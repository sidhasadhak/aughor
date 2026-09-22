"""HB-4 — the injection gate and its falsifier: a source kind reaches a prompt only
with measured lift; until then the block renders '' and every prompt is byte-identical.
Plus the lockstep guard: the receipt's block list and the live prompt's prepend chain
must not disagree about the hub-notes block (grounding.py admits the drift risk)."""
from __future__ import annotations

from pathlib import Path

from aughor.ontology.agent_notes import propose_note


def _file_a_note(conn="hb4conn"):
    out = propose_note(
        conn, "arrivals", target="object",
        table="promise:order_to_delivery.dispatch",
        note="carrier X was on strike last week",
        evidence="said in Slack thread C1:1712.001 by Ana",
        confidence="low",
        provenance={"source_kind": "conversation", "authority": "said",
                    "author": "Ana", "where": "#ops",
                    "observed_at": "2026-09-15T08:00:00Z",
                    "verification": "unverified"})
    assert out.ok and out.action == "staged"
    return out


def test_the_gate_holds_for_what_people_merely_said_even_with_notes_present():
    """CB-8 (2026-09-23) amended the resting state: the ONE kind through the gate is a note whose
    numbers the data confirmed (`conversation:measured`, `hub.claims`). A said, unchecked note —
    this one — is still stored and shown, never injected; the `conversation` kind as a whole still
    waits on measured lift."""
    _file_a_note()
    from aughor.hub.injection import INJECTABLE_SOURCE_KINDS, ranked_notes_block
    assert INJECTABLE_SOURCE_KINDS == ("conversation:measured",)
    assert "conversation" not in INJECTABLE_SOURCE_KINDS
    assert ranked_notes_block("hb4conn") == ""      # unchecked: stored and shown, never injected


def test_the_grounding_producer_is_byte_inert_while_the_gate_holds():
    _file_a_note()
    from aughor.agent.grounding import hub_notes
    assert hub_notes("hb4conn") == ""


def test_a_graduated_kind_renders_ranked_and_stamped(monkeypatch):
    _file_a_note(conn="hb4conn2")
    monkeypatch.setattr("aughor.hub.injection.INJECTABLE_SOURCE_KINDS", ("conversation",))
    from aughor.hub.injection import ranked_notes_block
    block = ranked_notes_block("hb4conn2")
    assert "CONTEXT FROM PEOPLE" in block
    assert "carrier X was on strike last week" in block
    assert "[said by Ana in #ops" in block          # the stamp travels


def test_the_two_prompt_seams_stay_in_lockstep():
    """The receipt's `_BLOCKS` list and `_stream_chat`'s prepend chain are two
    orderings of the same blocks, and nothing else fails when they disagree — so
    THIS does: the hub-notes block must appear in both, or in neither."""
    from aughor.agent import grounding
    keys = [b[0] for b in grounding._BLOCKS]
    assert "hub_notes" in keys, "the receipt lost the hub-notes block"
    live = Path("aughor/routers/investigations.py").read_text()
    assert "hub_notes" in live, "the live prompt lost the hub-notes prepend"


# ── the harness arm: exists, ungated, and inert-dropped honestly ──────────────────

def test_the_notes_arm_is_declared_and_its_context_is_ungated():
    import evals.ablation_eval as ev
    assert "notes" in ev.ARMS
    _file_a_note(conn="hb4conn3")
    # UNGATED: the arm measures what the gate asks, so it renders while the gate holds.
    ctx = ev.notes_context("hb4conn3")
    assert "carrier X was on strike" in ctx and "CONTEXT FROM PEOPLE" in ctx


def test_the_notes_arm_drops_inert_rather_than_spending():
    import evals.ablation_eval as ev
    arms, dropped = ev._arms_after_notes_check(("raw", "notes"), "")
    assert arms == ("raw",) and dropped == ("notes",)
    arms2, dropped2 = ev._arms_after_notes_check(("raw", "notes"), "some block")
    assert arms2 == ("raw", "notes") and dropped2 == ()
