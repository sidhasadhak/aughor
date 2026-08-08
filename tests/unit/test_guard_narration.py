"""The narration half of the guard receipts (Wave 2 / Layer 2.2).

A4 (#271) made every silent rewrite emit a `guard_receipt` frame and B2 renders them,
so the interventions are visible in the UI. This is P1's other half: the ANSWERING
model sees them too, so a correction is explained in the answer's own voice instead of
arriving only as a clause bolted onto the headline.

The defect these tests pin: the narrator was handed `answer.headline` — the raw model
claim — while the user was shown `_grounded_headline`, which the grounding rewrite had
corrected and the guards had appended cautions to. The prose could therefore restate,
with confidence, a number the headline had already retracted.
"""
from __future__ import annotations

from aughor.routers.investigations import _GUARD_PROSE, _guard_note


def test_a_clean_turn_adds_nothing():
    """No intervention ⇒ no note ⇒ the prompt is byte-identical to before. A guard
    that ran and found nothing is not news."""
    assert _guard_note({}) == ""
    assert _guard_note({"compiled": True, "lint": True}) == ""


def test_a_correction_is_narrated():
    note = _guard_note({"grounded": True})
    assert "did not match the result cells" in note
    assert "ONE plain sentence" in note


def test_every_flag_that_changed_the_answer_is_covered():
    """The flags that rewrite or qualify what the user reads must all be speakable —
    a guard that silently changes an answer and cannot explain itself is the failure
    mode this item exists to close."""
    for key in ("grounded", "defan", "narration_inversion", "measure_grain", "id_arithmetic"):
        assert _guard_note({key: True}), f"{key} has no prose"
        assert key in _GUARD_PROSE


def test_flags_that_did_not_change_the_answer_stay_silent():
    """`compiled` and `lint` are how the answer was BUILT, not something the reader
    must account for. Narrating them would train the reader to skip the prose."""
    assert "compiled" not in _GUARD_PROSE
    assert "lint" not in _GUARD_PROSE


def test_trust_check_messages_not_pattern_ids_reach_the_model():
    """`e1_checks` holds identifiers for the receipt; the narrator needs the prose.
    'ratio_denominator' explains nothing to a reader."""
    note = _guard_note({"e1_checks": ["ratio_denominator"],
                        "e1_messages": ["the denominator mixes two populations"]})
    assert "the denominator mixes two populations" in note
    assert "ratio_denominator" not in note


def test_at_most_two_trust_messages(monkeypatch):
    note = _guard_note({"e1_messages": ["one", "two", "three"]})
    assert "one" in note and "two" in note and "three" not in note


def test_multiple_interventions_are_all_listed():
    note = _guard_note({"grounded": True, "measure_grain": True})
    assert note.count("\n- ") == 2


def test_the_note_forbids_restating_the_number():
    """The model must explain what happened, not relitigate the corrected value —
    re-deriving it is how a narration pass reintroduces the claim the guard removed."""
    note = _guard_note({"grounded": True})
    assert "Do not restate the number" in note


def test_the_narrator_is_fed_the_grounded_headline_not_the_raw_one():
    """The seam itself, pinned against regression: the prompt builder must read the
    corrected headline. Asserted on the source because the surrounding generator needs
    a live DB, a provider and a full request to run."""
    import inspect

    from aughor.routers import investigations

    src = inspect.getsource(investigations)
    assert 'f"Answer: {_grounded_headline}\\n"' in src, (
        "the narrator prompt must carry the grounded/caveated headline — the raw "
        "answer.headline lets the narrative contradict what the user was shown")
    assert 'f"Answer: {answer.headline}\\n"' not in src


# ── Wave 3 / 2.3: the disclosed assumption ───────────────────────────────────

def test_answer_anyway_is_disclosed_not_silent():
    """"Answer anyway" already shipped in the UI; what it never did was record that an
    assumption was made. An answer resting on one of several readings must say so."""
    note = _guard_note({"assumed": True})
    assert "more than one reasonable reading" in note
    assert "say which one you answered" in note


def test_an_unambiguous_turn_discloses_nothing():
    assert _guard_note({"assumed": False}) == ""


def test_assumption_rides_with_the_guard_notes():
    """One list, one instruction — everything the reader must account for arrives in
    the same sentence rather than as a second mechanism."""
    note = _guard_note({"assumed": True, "grounded": True})
    assert note.count("\n- ") == 2
