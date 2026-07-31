"""Wave S2 — the trusted-query provenance that never reached the receipt.

Measured on main before the fix: the chat answer path writes its trusted-query lineage as
``("trusted", "query:<question>", note)`` (`routers/investigations.py`), and
``_guards_from_lineage`` kept an edge only when its ref started with ``guard:``. So **every
trusted edge ever written was dropped**, and the frontend branch that renders one —
`WhyThisNumber.tsx`, ``action === "trusted"`` → "reused a trusted query" — was unreachable
code. Both ends were built and only the middle was missing.

What makes this worth surfacing rather than merely fixing: the note is the promoter's own
warrant sentence, and it is scrupulous about what it does and does not claim —
"Consistency-verified (reproduces this connection's prior answer), NOT independently checked
for correctness." A badge that rendered "verified" over that would launder the weaker warrant
into the stronger one, in exactly the place a user is deciding whether to believe a number.
So the caveat rides through verbatim.
"""
from __future__ import annotations

from aughor.trust.receipt import _guards_from_lineage

EVAL_WARRANT = ("Verified by eval suite 70efbc7c53d5: passed in all 11 runs. "
                "Consistency-verified (reproduces this connection's prior answer), "
                "NOT independently checked for correctness.")


def test_a_trusted_edge_survives_into_the_receipt():
    """The regression itself: a `query:`-prefixed trusted edge used to vanish."""
    rows = _guards_from_lineage([
        {"relation": "trusted", "ref": "query:How many rows are in the returns table?",
         "detail": EVAL_WARRANT},
    ])

    assert len(rows) == 1, "the trusted edge was dropped — the receipt lost its provenance"
    assert rows[0]["action"] == "trusted"
    assert rows[0]["name"] == "How many rows are in the returns table?"


def test_the_authored_warrant_rides_through_verbatim():
    """The sentence distinguishing consistency-verified from human-checked is the product.
    Shortening or rewording it here would be the laundering this exists to prevent."""
    rows = _guards_from_lineage([
        {"relation": "trusted", "ref": "query:q", "detail": EVAL_WARRANT},
    ])
    assert rows[0]["caveat"] == EVAL_WARRANT
    assert "NOT independently checked" in rows[0]["caveat"]


def test_guard_edges_are_unchanged():
    """The existing contract holds — this widened the filter, it did not replace it."""
    rows = _guards_from_lineage([
        {"relation": "flagged", "ref": "guard:ambiguous_question", "detail": "under-specified"},
        {"relation": "validated_by", "ref": "guard:join_domain", "detail": ""},
    ])
    assert [r["name"] for r in rows] == ["ambiguous_question", "join_domain"]
    assert [r["action"] for r in rows] == ["flagged", "validated_by"]


def test_unrelated_lineage_is_still_excluded():
    """A receipt's guard list is not a dumping ground for every edge — source SQL, input
    tables and metric edges stay out, or the panel that renders guards becomes noise."""
    rows = _guards_from_lineage([
        {"relation": "source_sql", "ref": "sql", "detail": "SELECT 1"},
        {"relation": "input", "ref": "table:orders", "detail": None},
        {"relation": "metric_used", "ref": "metric:gmv", "detail": "matched"},
    ])
    assert rows == []


def test_a_trusted_edge_with_no_colon_still_names_something():
    """Defensive: a ref written without the `query:` prefix must not produce an empty name
    (an unnamed row in a provenance panel is worse than no row)."""
    rows = _guards_from_lineage([
        {"relation": "trusted", "ref": "some-pattern", "detail": "note"},
    ])
    assert rows[0]["name"] == "some-pattern"


def test_the_real_chat_lineage_shape_end_to_end():
    """The exact tuple shape `routers/investigations.py` appends, mixed with a real guard —
    pinned so a future edit to either side cannot re-open the gap silently."""
    lineage = [
        {"relation": "source_sql", "ref": "sql", "detail": "SELECT count(*) FROM returns"},
        {"relation": "flagged", "ref": "guard:ambiguous_question", "detail": "under-specified"},
        {"relation": "trusted", "ref": "query:How many rows are in the returns table?",
         "detail": EVAL_WARRANT},
    ]
    rows = _guards_from_lineage(lineage)

    assert {r["action"] for r in rows} == {"flagged", "trusted"}
    trusted = next(r for r in rows if r["action"] == "trusted")
    assert trusted["fired"] is True
    assert trusted["caveat"] == EVAL_WARRANT
