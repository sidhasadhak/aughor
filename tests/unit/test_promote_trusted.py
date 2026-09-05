"""Wave L5 — verified eval cases become trusted queries.

The trusted-query store shipped with ZERO entries on every connection: built, wired,
never adopted. The eval plane had been accumulating exactly what it wants. This is the
capture half of capture → verify → generalize, and the tests are mostly about what it
refuses to capture.
"""
from __future__ import annotations

from aughor.evals import promote_trusted as PT


def _wire(monkeypatch, *, cases, runs, results):
    monkeypatch.setattr("aughor.evals.store.list_cases", lambda sid, limit=1000: cases)
    monkeypatch.setattr("aughor.evals.store.list_runs", lambda sid, limit=50: runs)
    monkeypatch.setattr("aughor.evals.store.run_results",
                        lambda rid, limit=5000: results[rid])


def _case(cid, q="How many returns?", sql="SELECT COUNT(*) FROM returns"):
    return {"id": cid, "question": q, "artifact": sql, "expected": {"tables": ["returns"]}}


def test_a_case_passing_every_run_is_promotable(monkeypatch):
    _wire(monkeypatch,
          cases=[_case("c1")],
          runs=[{"id": "r1", "status": "succeeded"}, {"id": "r2", "status": "succeeded"}],
          results={"r1": [{"case_id": "c1", "passed": True}],
                   "r2": [{"case_id": "c1", "passed": True}]})
    assert [p["case"]["id"] for p in PT.promotable("s1")] == ["c1"]


def test_a_case_whose_result_depends_on_configuration_is_not_promotable(monkeypatch):
    """Passing in one cell and failing in another means correctness is CONDITIONAL, and
    a conditionally-correct query is the last thing to hand the planner as trusted."""
    _wire(monkeypatch,
          cases=[_case("c1")],
          runs=[{"id": "r1", "status": "succeeded"}, {"id": "r2", "status": "succeeded"}],
          results={"r1": [{"case_id": "c1", "passed": True}],
                   "r2": [{"case_id": "c1", "passed": False}]})
    assert PT.promotable("s1") == []


def test_one_observation_is_an_anecdote(monkeypatch):
    _wire(monkeypatch,
          cases=[_case("c1")],
          runs=[{"id": "r1", "status": "succeeded"}],
          results={"r1": [{"case_id": "c1", "passed": True}]})
    assert PT.promotable("s1") == []


def test_unfinished_runs_do_not_vouch_for_anything(monkeypatch):
    _wire(monkeypatch,
          cases=[_case("c1")],
          runs=[{"id": "r1", "status": "succeeded"}, {"id": "r2", "status": "running"}],
          results={"r1": [{"case_id": "c1", "passed": True}], "r2": []})
    assert PT.promotable("s1") == []


def test_the_id_is_content_addressed_so_re_promotion_is_idempotent():
    """`save_trusted` dedupes on id, which makes a blank id overwrite every entry with
    the next and a random id duplicate everything on re-run. Hashing the question is
    the only option that is safe in both directions."""
    a = PT.trusted_id("conn", "How many returns?")
    b = PT.trusted_id("conn", "  how many returns?  ")
    assert a == b and a.startswith("tq_")
    assert PT.trusted_id("other", "How many returns?") != a


def test_the_minted_note_refuses_to_claim_correctness(monkeypatch):
    """These come from a CONSISTENCY suite: passing means 'reproduces the answer this
    connection already gave', not 'is true'. A store called `trusted` invites exactly
    that misreading, so every entry says which warrant it has."""
    saved: list = []
    _wire(monkeypatch,
          cases=[_case("c1")],
          runs=[{"id": "r1", "status": "succeeded"}, {"id": "r2", "status": "succeeded"}],
          results={"r1": [{"case_id": "c1", "passed": True}],
                   "r2": [{"case_id": "c1", "passed": True}]})
    monkeypatch.setattr("aughor.semantic.trusted_queries.list_trusted",
                        lambda c, include_unapproved=False: [])
    monkeypatch.setattr("aughor.semantic.trusted_queries.save_trusted", saved.append)

    out = PT.promote("s1", "conn")
    assert out["promoted"] == 1
    note = saved[0].note.lower()
    assert "not independently checked" in note and "consistency" in note
    assert PT.SOURCE_TAG in saved[0].tags


def test_the_prompt_header_states_the_weakest_warrant_present():
    """Claiming KNOWN-CORRECT over a set containing an eval-verified entry would
    launder the weaker warrant into the stronger one, in a prompt whose whole job is
    to be believed."""
    from aughor.semantic.trusted_queries import TrustedQuery, build_trusted_block

    def _tq(tags):
        return (TrustedQuery(id="i", connection_id="c", question="q", sql="SELECT 1",
                             tags=tags), 1.0)

    assert "KNOWN-CORRECT" in build_trusted_block([_tq(["curated"])])
    mixed = build_trusted_block([_tq(["curated"]), _tq([PT.SOURCE_TAG])])
    assert "KNOWN-CORRECT" not in mixed and "eval-verified" in mixed
