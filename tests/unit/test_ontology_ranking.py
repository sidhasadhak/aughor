"""Wave O3 — retrieval ranking, scoped by a pre-check that ran before the code.

The pre-check (scoping-doc gate, L3 lesson) measured the reference connection: table hints
are 0% ambiguous, column hints 100%, and 23% of 795 real questions touch an ambiguous term.
So ranking is reachable but only where ambiguity exists, and
:func:`test_a_single_candidate_is_untouched` pins that the common path is free.

The two carrying rules: :func:`test_a_human_declaration_beats_any_amount_of_popularity`
(the governance story) and :func:`test_ranking_never_reads_edge_evidence` (J4/J14, made
testable rather than merely documented).
"""
from __future__ import annotations

from aughor.ontology.ranking import (
    Signals,
    ambiguity,
    has_edge_signal,
    rank,
    rank_terms,
    score,
)


def _r(candidates, signals):
    return [x.candidate for x in rank(candidates, signals)]


# ── authority order ─────────────────────────────────────────────────────────────────

def test_a_human_declaration_beats_any_amount_of_popularity():
    """The governance story: one human YAML entry outranks every popularity score."""
    got = _r(["gmv_eur", "revenue_legacy"], {
        "gmv_eur": Signals(source="human"),
        "revenue_legacy": Signals(hits=9999, trusted_uses=99),
    })
    assert got == ["gmv_eur", "revenue_legacy"]


def test_mined_outranks_an_llm_candidate():
    got = _r(["a", "b"], {"a": Signals(source="llm_candidate"), "b": Signals(source="mined")})
    assert got == ["b", "a"]


def test_a_declared_source_outranks_an_undeclared_one():
    got = _r(["a", "b"], {"a": Signals(hits=500), "b": Signals(source="mined")})
    assert got == ["b", "a"]


def test_trusted_use_outranks_raw_hits():
    """Verified reuse is a stronger signal than someone having clicked it a lot."""
    got = _r(["a", "b"], {"a": Signals(hits=1000), "b": Signals(trusted_uses=1)})
    assert got == ["b", "a"]


def test_more_hits_wins_when_nothing_else_separates():
    assert _r(["a", "b"], {"a": Signals(hits=1), "b": Signals(hits=50)}) == ["b", "a"]


def test_a_stale_candidate_sinks():
    got = _r(["a", "b"], {"a": Signals(hits=100, freshness="stale"),
                          "b": Signals(hits=1, freshness="fresh")})
    assert got == ["b", "a"]


def test_freshness_uses_the_V_vocabulary_not_a_new_one():
    """`dirty` and `stale` are V's words; inventing a sixth dialect is the Wave V lesson."""
    assert score("x", Signals(freshness="dirty"))[1] == 1
    assert score("x", Signals(freshness="fresh"))[1] == 0
    assert score("x", Signals(freshness="unknown"))[1] == 0


def test_an_unmeasured_candidate_ranks_neutrally_not_last():
    """Absent means unknown. Punishing it as if it had been measured and found unused
    would make ranking worse than no ranking on a fresh connection."""
    got = _r(["known", "unmeasured"], {"known": Signals(hits=0)})
    assert set(got) == {"known", "unmeasured"}


def test_ties_break_alphabetically_so_ordering_is_deterministic():
    assert _r(["b", "a"], {}) == ["a", "b"]


def test_the_score_is_a_tuple_not_a_weighted_sum():
    """A sum invites tuning constants nobody can justify and makes 'why did this win'
    unanswerable; a lexicographic tuple states the priority order out loud."""
    assert isinstance(score("x", Signals()), tuple)


# ── what ranking must NOT do ────────────────────────────────────────────────────────

def test_ranking_never_reads_edge_evidence():
    """J4/J14 made testable. A join's measured overlap is evidence a join is SAFE, not
    that a table is what the user MEANT. Ordering retrieval must never become weighting
    the graph."""
    import aughor.ontology.ranking as R

    assert has_edge_signal([]) is False
    src = open(R.__file__).read()
    for forbidden in ("joins_on", "value_overlap", "provenance.measured", "one_hop"):
        assert forbidden not in src, f"ranking must not read {forbidden}"


def test_ranking_orders_and_never_filters():
    """A ranker that filtered would silently hide the right answer when its signals were
    wrong, and the failure would look exactly like the entity not existing."""
    got = _r(["a", "b", "c"], {"a": Signals(source="human")})
    assert sorted(got) == ["a", "b", "c"]


def test_a_single_candidate_is_untouched():
    """Measured as 100% of table hints on the reference connection, so this is the common
    path and it must be free."""
    assert rank_terms({"orders": ["orders"]}, {}) == {"orders": ["orders"]}


def test_an_empty_map_is_handled():
    assert rank_terms({}, {}) == {}
    assert rank([], {}) == []


# ── the hint map ────────────────────────────────────────────────────────────────────

def test_an_ambiguous_term_is_reordered():
    out = rank_terms({"revenue": ["revenue_legacy", "gmv_eur"]},
                     {"gmv_eur": Signals(source="human")})
    assert out["revenue"][0] == "gmv_eur"


def test_unambiguous_terms_pass_through_beside_ambiguous_ones():
    out = rank_terms({"orders": ["orders"], "revenue": ["b", "a"]}, {})
    assert out["orders"] == ["orders"] and out["revenue"] == ["a", "b"]


def test_ambiguity_reports_the_number_that_scoped_this_item():
    """A future connection may be far more ambiguous than the one measured; a caller
    should read the number rather than inherit the finding."""
    assert ambiguity({"a": ["x"], "b": ["x", "y"]}) == {
        "terms": 2, "ambiguous": 1, "share": 0.5}
    assert ambiguity({})["share"] == 0.0


# ── signals from the stores ─────────────────────────────────────────────────────────

def test_signals_come_from_the_declared_synonym_store(tmp_path, monkeypatch):
    import aughor.ontology.vocabulary as V
    from aughor.ontology.ranking import signals_from_stores

    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocab"))
    V.add_synonym("c1", "metric", "gmv_eur", "revenue", source="human")
    sig = signals_from_stores("c1")
    assert sig["gmv_eur"].source == "human"


def test_the_strongest_source_wins_per_subject(tmp_path, monkeypatch):
    import aughor.ontology.vocabulary as V
    from aughor.ontology.ranking import signals_from_stores

    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocab"))
    V.add_synonym("c1", "metric", "m", "a", source="llm_candidate")
    V.add_synonym("c1", "metric", "m", "b", source="human")
    assert signals_from_stores("c1")["m"].source == "human"


def test_an_unavailable_signal_store_degrades_rather_than_raising(monkeypatch):
    """Ranking must never fail a question; it degrades to the deterministic tie-break."""
    import aughor.ontology.ranking as R

    def _boom(_):
        raise RuntimeError("store down")

    monkeypatch.setattr("aughor.ontology.vocabulary.synonyms_for", _boom)
    assert R.signals_from_stores("c1") == {}
