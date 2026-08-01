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


# ── the deep path (Wave S2, second half) ─────────────────────────────────────────
#
# `guard_edges` used to be passed at exactly ONE call site — the chat path — so a deep
# answer's receipt carried no guards at all and structurally could not report that it had
# reused a verified pattern, while a quick answer on the same question could.
#
# These seed their OWN trusted library. `data/trusted_queries.json` is untracked, so a test
# that read the developer's copy would pass here and fail on a fresh checkout — the same
# "measuring the machine, not the code" mistake this wave already made once.

import json
import pytest


@pytest.fixture()
def seeded_library(tmp_path, monkeypatch):
    """A two-entry trusted library, with the warrant sentence the promoter really writes."""
    from aughor.semantic import trusted_queries as tq

    store = tmp_path / "trusted_queries.json"
    store.write_text(json.dumps([
        {"id": "tq1", "connection_id": "c1",
         "question": "How many rows are in the returns table?",
         "sql": "SELECT count(*) FROM returns", "tables": ["returns"],
         "note": EVAL_WARRANT, "tags": ["from_eval"]},
        {"id": "tq2", "connection_id": "c1",
         "question": "How many returns by reason were logged?",
         "sql": "SELECT reason, count(*) FROM returns GROUP BY reason",
         "tables": ["returns"], "note": EVAL_WARRANT, "tags": ["from_eval"]},
    ]))
    monkeypatch.setattr(tq, "_PATH", store)
    return store


def _du(question: str, connection_id: str = "c1"):
    from aughor.semantic.data_understanding import build_data_understanding
    return build_data_understanding(None, connection_id=connection_id, question=question)


def test_the_deep_intake_records_which_trusted_patterns_it_used(seeded_library):
    du = _du("How many rows are in the returns table?")
    assert du.trusted_block, "precondition: this question matches the seeded library"
    assert du.trusted_used, "the block went into the prompt but nothing recorded what was in it"
    assert du.trusted_used[0]["question"] == "How many rows are in the returns table?"
    assert "NOT independently checked" in du.trusted_used[0]["note"]


def test_a_question_matching_nothing_records_nothing(seeded_library):
    """The list and the claim must never disagree: no block ⇒ no provenance."""
    du = _du("zzz nonsense qqq about unrelated widgets")
    assert du.trusted_block == ""
    assert du.trusted_used == []


def test_the_deep_edges_reduce_to_the_same_receipt_rows_as_chat(seeded_library):
    """One receipt reader serves both paths — the deep edge shape is the chat edge shape."""
    du = _du("How many rows are in the returns table?")
    edges = [{"relation": "trusted", "ref": f"query:{t['question'][:60]}", "detail": t["note"]}
             for t in du.trusted_used]

    rows = _guards_from_lineage(edges)

    assert len(rows) == len(du.trusted_used) > 0
    assert {r["action"] for r in rows} == {"trusted"}
    assert rows[0]["caveat"] == du.trusted_used[0]["note"]


# ── the unified receipt carries what only the old panel could show (Wave S2) ──────
#
# `TrustReceipt.tsx` and `WhyThisNumber.tsx` both render on the same answer, and the
# arc doc calls collapsing them "unavoidable S2 work". But the older panel is not a
# duplicate: it alone showed resolved readings, the Learning Receipt and the Activation
# Receipt, none of which the unified projection carried. Measured over 835 answer
# receipts: learning on 27, activations on 2, and 26 resolved_ambiguity edges. Deleting
# the panel first would have destroyed those.

def _raw(payload: dict, lineage: list) -> dict:
    """The shape `build_public_receipt` actually takes: {artifact, lineage, job, cost}."""
    return {
        "artifact": {"id": "art1", "kind": "chat_answer", "conn_id": "c1", "version": 1,
                     "created_at": "2026-07-31T00:00:00Z", "payload": payload},
        "lineage": lineage, "job": None, "cost": None,
    }


def _build(payload=None, lineage=None, signed=False):
    from aughor.trust.receipt import build_public_receipt
    return build_public_receipt(_raw(payload or {}, lineage or []), signed=signed)


def test_resolved_readings_reach_the_unified_receipt():
    r = _build(lineage=[{"relation": "resolved_ambiguity", "ref": "reading:revenue = net",
                         "detail": "settled on 2026-07-02 by a reviewer"}])
    assert r["resolved_readings"] == [
        {"reading": "revenue = net", "note": "settled on 2026-07-02 by a reviewer"}]


def test_learning_and_activations_reach_the_unified_receipt():
    r = _build(payload={
        "learning": {"readings_reused": 2, "resolutions_crystallized": 1,
                     "corrections_applied": 0, "trusted_program_replayed": 0},
        "activations": [{"capability": "deep_analysis.premise_check", "reason": "a claim was checkable",
                         "count": 1}],
    })
    assert r["learning"]["resolutions_crystallized"] == 1
    assert r["activations"][0]["capability"] == "deep_analysis.premise_check"


def test_an_answer_that_learned_nothing_says_so_without_inventing_shape():
    """Null, not an empty learning object: a zeroed Learning Receipt would render as
    'the loop ran and learned nothing', which is a different claim from 'no loop ran'."""
    r = _build()
    assert r["learning"] is None
    assert r["activations"] == []
    assert r["resolved_readings"] == []


def test_the_new_fields_are_inside_the_signature():
    """Additive fields still have to be tamper-evident, or the collapse would move
    evidence from a signed surface to an unsigned one."""
    from aughor.trust.receipt import verify
    signed = _build(payload={"learning": {"readings_reused": 1, "resolutions_crystallized": 0,
                                          "corrections_applied": 0,
                                          "trusted_program_replayed": 0}}, signed=True)
    assert verify(signed) is True

    signed["learning"]["readings_reused"] = 99
    assert verify(signed) is False, "the learning receipt is outside the signature"
