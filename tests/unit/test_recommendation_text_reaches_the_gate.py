"""The recommendation a person pressed Execute on is what departs — and what is gated.

🔴 It was not. `routers/actions.py` read `report["recommended_actions"]` and each item's
`text`; every stored report carries `recommendations` with items keyed `action`. Measured
2026-09-19 on the live history: of the reports holding recommendations, all use
`recommendations` and none uses `recommended_actions`.

The cost was not a blank message, which is why it survived. `rec_text` silently stayed the
placeholder ``"Recommendation #N from investigation X"``, and that placeholder was
dispatched to the trigger **and handed to the departure gate as its `text`**. So HB-2 law
1 — every stated magnitude must sit in the measurement the message departs on — was asked
about a sentence containing no magnitudes, and passed. **A recommendation full of numbers
departed past a gate that never saw it.**

These tests pin the text at the two places it matters: what the gate inspects, and what
the payload carries.
"""
from __future__ import annotations

import json

import pytest

REPORT = {
    "headline": "Revenue fell 12.4% in March",
    "recommendations": [
        {"action": "Reconcile the revenue metric — SUM(order_items.sale_price) returned "
                   "1,204,551 against the registry's 1,180,002.",
         "expected_impact": "removes a 24,549 discrepancy", "owner": "Finance",
         "timeline": "this week"},
        {"action": "Re-run the category breakdown with the six omitted groups.",
         "expected_impact": "", "owner": "", "timeline": ""},
    ],
}


FALLBACK = "Recommendation #0 from investigation inv1"


def test_the_recommendation_text_is_read_not_the_placeholder():
    """The defect itself: the wrong field made every extraction fall through, and the
    placeholder is what the gate then inspected."""
    from aughor.routers.actions import recommendation_text

    got = recommendation_text(REPORT, 0, FALLBACK)
    assert "1,204,551" in got and "1,180,002" in got
    assert got != FALLBACK


def test_it_reads_the_stored_shape_as_JSON_TEXT_too():
    """`report_json` is a TEXT column; the route hands whatever the row holds."""
    from aughor.routers.actions import recommendation_text

    assert "1,204,551" in recommendation_text(json.dumps(REPORT), 0, FALLBACK)


def test_the_older_field_name_still_works_as_a_fallback():
    """The report prompt still names `recommended_actions`, so a hand-built or older
    report may use it. A fallback costs nothing; assuming history costs a placeholder."""
    from aughor.routers.actions import recommendation_text

    old = {"recommended_actions": [{"text": "Raise the row limit to 200."}]}
    assert recommendation_text(old, 0, FALLBACK) == "Raise the row limit to 200."
    assert recommendation_text({"recommended_actions": ["A bare string."]}, 0,
                               FALLBACK) == "A bare string."


@pytest.mark.parametrize("report, index", [
    ({"recommendations": []}, 0),          # nothing to point at
    (REPORT, 9),                           # out of range
    (REPORT, -1),                          # negative never wraps to the last one
    ({"recommendations": [{"action": "   "}]}, 0),   # present but empty
    ("not json at all", 0),
    (None, 0),
])
def test_anything_unreadable_falls_back_rather_than_inventing(report, index):
    """The placeholder is the honest answer when there is nothing to quote — the defect
    was never the fallback, it was falling back SILENTLY on every well-formed report."""
    from aughor.routers.actions import recommendation_text

    assert recommendation_text(report, index, FALLBACK) == FALLBACK


def test_a_negative_index_does_not_read_the_last_recommendation():
    """Python's negative indexing would have quietly dispatched a different
    recommendation than the one clicked."""
    from aughor.routers.actions import recommendation_text

    assert recommendation_text(REPORT, -1, FALLBACK) == FALLBACK


def test_the_route_hands_the_gate_what_this_function_returns():
    """The two halves must stay joined: extracting the text is worthless if the route
    gates something else. Pinned on the source because standing up the gate, the trigger
    store and the dispatcher to assert one argument would test those instead."""
    import inspect

    from aughor.routers import actions as mod

    src = inspect.getsource(mod.execute_recommendation_action)
    assert "rec_text = recommendation_text(" in src
    assert "text=rec_text" in src          # what the departure gate inspects
    assert "recommendation=rec_text" in src  # what actually leaves
    # And the silent swallow is gone: a failure is tolerated with a counter, and a
    # placeholder that does depart says so.
    assert "except Exception:\n        pass" not in src
    assert "logger.warning" in src
