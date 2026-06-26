"""Sub-question id integrity (2026-06-26).

The exploration planner is an LLM and sometimes emits duplicate ids (observed: two
`Q3`) or gaps. Every piece of downstream state keys off the sub-question id —
subq_answers, subq_data_portrait, refinement injection, and the React stepper key —
so a collision silently cross-contaminates two distinct questions AND crashes the
frontend with `Encountered two children with the same key, sq-Q3`.

`_canonicalize_subq_ids` reindexes the planned chain to a contiguous, unique Q1..Qn
(remapping depends_on); `_unique_subq_id` protects the runtime-promoted insert path.
See aughor/agent/explore.py.
"""
from aughor.agent.explore import _canonicalize_subq_ids, _unique_subq_id
from aughor.agent.state import SubQuestion


def _sq(id, purpose="relationship", depends_on=None):
    return SubQuestion(
        id=id, purpose=purpose, depends_on=depends_on or [],
        question=f"question {id}", expected_output="a small aggregate",
    )


def test_duplicate_ids_are_reindexed_to_unique_sequence():
    # Planner emitted two distinct sub-questions both labelled Q3 (the live bug).
    chain = [_sq("Q1", "landscape"), _sq("Q2"), _sq("Q3"), _sq("Q3"), _sq("Q5")]
    out = _canonicalize_subq_ids(chain)
    ids = [s.id for s in out]
    assert ids == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert len(set(ids)) == len(ids), "ids must be unique"
    # Content order is preserved — only ids changed.
    assert [s.question for s in out] == [s.question for s in chain]


def test_depends_on_remapped_to_backward_reference():
    # Q4 (orig) depends on the SECOND Q3; after reindex it must point at the new id
    # of an EARLIER step, never forward, never at a dropped/unknown ref.
    chain = [_sq("Q1", "landscape"), _sq("Q3"), _sq("Q3"), _sq("Q4", depends_on=["Q3"])]
    out = _canonicalize_subq_ids(chain)
    assert [s.id for s in out] == ["Q1", "Q2", "Q3", "Q4"]
    # "Q3" old-id mapped to new Q2 and Q3; the backward ref from position 4 resolves
    # to the most recent earlier occurrence → Q3.
    assert out[3].depends_on == ["Q3"]


def test_forward_and_unknown_depends_on_are_dropped():
    chain = [_sq("Q1", "landscape", depends_on=["Q9", "Q2"]), _sq("Q2")]
    out = _canonicalize_subq_ids(chain)
    # Q1 can't depend on a later step (Q2) or an unknown id (Q9).
    assert out[0].depends_on == []


def test_empty_chain_is_passthrough():
    assert _canonicalize_subq_ids([]) == []


def test_unique_subq_id_avoids_collisions():
    existing = {"Q1", "Q2", "Q3"}
    nid = _unique_subq_id(existing)
    assert nid not in existing
    # And it keeps minting fresh ids as the set grows.
    existing.add(nid)
    assert _unique_subq_id(existing) not in existing
