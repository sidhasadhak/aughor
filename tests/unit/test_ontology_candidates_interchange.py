"""Wave O4 + O7 — the generalization loop and connection-as-code.

The carrying tests: :func:`test_an_unbound_candidate_is_never_offerable` (a suggestion
that cannot execute wastes the reviewer's attention AND teaches them the queue is noise,
which is how a review surface dies) and
:func:`TestInterchange.test_export_import_export_is_identical` (a lossy round-trip is
worse than no interchange, because it looks like a backup).
"""
from __future__ import annotations

import pytest

from aughor.ontology.candidates import (
    CANDIDATE_KINDS,
    ORIGINS,
    Candidate,
    CandidateError,
    bind,
    mine,
    mine_from_verdicts,
    offerable,
    to_inbox_items,
)
from aughor.ontology.interchange import (
    BUNDLE_VERSION,
    SECTIONS,
    bundle_from_yaml,
    export_bundle,
    plan_import,
    round_trips,
)


@pytest.fixture(autouse=True)
def vocab_root(tmp_path, monkeypatch):

    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocabulary"))


def _c(**kw) -> Candidate:
    base = {"connection_id": "c1", "kind": "join", "subject": "orders",
            "proposal": "orders.id = items.order_id", "origin": "trusted_query"}
    return Candidate(**{**base, **kw})


# ── O4: nothing auto-applies, nothing unbound is offered ────────────────────────────

def test_an_unbound_candidate_is_never_offerable():
    """A suggestion that cannot execute wastes the reviewer's attention AND teaches them
    the queue is noise — which is how a review surface dies."""
    c = bind(_c(), lambda _c: (False, "no such column"))
    assert c.bound is False and not c.offerable
    assert offerable([c]) == []


def test_a_bound_candidate_is_offerable():
    c = bind(_c(), lambda _c: (True, ""))
    assert c.offerable and offerable([c]) == [c]


def test_a_binder_that_raises_marks_it_unbound_not_bound():
    """Failing closed is the only safe direction: an exception means we do not KNOW
    whether it executes."""
    def _boom(_c):
        raise RuntimeError("connection down")

    c = bind(_c(), _boom)
    assert c.bound is False and "RuntimeError" in c.bind_error


def test_with_no_binder_nothing_is_offerable():
    """A deployment that has not wired a binder must not start showing unverified SQL."""
    report = mine("c1", trusted_queries=[{"sql": "SELECT 1 JOIN x", "tables": ["orders"]}])
    assert report.candidates and report.offered == []


def test_the_summary_always_states_what_was_refused():
    """A miner reporting only successes looks like it found less than it did, and hides a
    broken binder."""
    report = mine("c1", trusted_queries=[{"sql": "a JOIN b", "tables": ["orders"]}],
                  binder=lambda _c: (False, "nope"))
    assert "1 refused" in report.summary()


# ── O4: what may be mined ───────────────────────────────────────────────────────────

def test_only_accepted_verdicts_are_mined():
    """A rejected correction is evidence about what is WRONG, not a proposal to
    generalize — mining it would propose the mistake."""
    rows = [{"verdict": "accepted", "subject": "gmv", "correction": "revenue"},
            {"verdict": "rejected", "subject": "bad", "correction": "worse"}]
    got = mine_from_verdicts("c1", rows)
    assert [c.subject for c in got] == ["gmv"]


def test_a_mined_candidate_carries_its_rank_and_origin():
    """A mined join and a human-declared one are not the same claim."""
    got = mine_from_verdicts("c1", [{"verdict": "accepted", "subject": "s",
                                     "correction": "p"}])[0]
    assert got.source_rank == "mined" and got.origin == "verdict"
    assert got.evidence


@pytest.mark.parametrize("kw,match", [
    ({"kind": "vibes"}, "unknown candidate kind"),
    ({"origin": "a dream"}, "unknown candidate origin"),
    ({"subject": " "}, "needs a subject"),
    ({"proposal": ""}, "needs a subject and a proposal"),
])
def test_junk_is_refused_at_construction(kw, match):
    """Junk reaching the queue teaches the reviewer to skim it."""
    with pytest.raises(CandidateError, match=match):
        _c(**kw).validate()


def test_the_vocabularies_are_typed_and_closed():
    assert "join" in CANDIDATE_KINDS and "synonym" in CANDIDATE_KINDS
    assert "verdict" in ORIGINS and "dbt" in ORIGINS


def test_inbox_items_are_returned_not_written():
    """J10 — ONE queue. Returning items keeps the A4 inbox the single writer, so O4 does
    not become a second suggestion store."""
    import aughor.ontology.candidates as C

    c = bind(_c(), lambda _c: (True, ""))
    items = to_inbox_items([c])
    assert items[0]["kind"] == "ontology.join" and items[0]["source_rank"] == "mined"
    assert not [n for n in dir(C) if n.startswith(("save_", "write_", "apply_"))]


def test_unbound_candidates_never_reach_the_inbox():
    c = bind(_c(), lambda _c: (False, "no"))
    assert to_inbox_items([c]) == []


# ── O7: the round-trip is the gate ──────────────────────────────────────────────────

class TestInterchange:
    def test_an_empty_connection_exports_every_section(self):
        b = export_bundle("c1").to_dict()
        assert b["version"] == BUNDLE_VERSION
        assert set(b["sections"]) == set(SECTIONS)

    def test_export_carries_the_real_store_contents(self):
        from aughor.ontology.vocabulary import add_synonym

        add_synonym("c1", "metric", "gmv_eur", "revenue", source="human")
        b = export_bundle("c1").to_dict()
        assert b["sections"]["synonyms"][0]["synonym"] == "revenue"

    def test_export_import_export_is_identical(self):
        """THE gate. Anything less means one direction is lossy, and a lossy round-trip
        is worse than no interchange because it looks like a backup."""
        from aughor.ontology.vocabulary import add_synonym, set_value_dictionary

        add_synonym("c1", "metric", "gmv_eur", "revenue", source="human")
        add_synonym("c1", "table", "orders", "sales", source="mined")
        set_value_dictionary("c1", "products", "category", ["womenswear"])
        assert round_trips("c1")

    def test_importing_into_a_fresh_connection_adds_everything(self):
        from aughor.ontology.vocabulary import add_synonym

        add_synonym("src", "metric", "m", "revenue", source="human")
        bundle = export_bundle("src").to_dict()
        plan = plan_import("dest", bundle)
        assert len(plan.additions) == 1 and plan.clean

    def test_a_collision_is_reported_not_resolved(self):
        """Overwriting a human's curation with a file's version is a decision a human
        makes. An importer that silently won is how connection-as-code becomes
        whoever-imported-last-wins."""
        from aughor.ontology.vocabulary import add_synonym

        add_synonym("dest", "metric", "m", "revenue", source="human")
        bundle = {"version": BUNDLE_VERSION, "connection_id": "src", "sections": {
            "synonyms": [{"subject_kind": "metric", "subject_id": "m",
                          "synonym": "revenue", "source": "llm_candidate"}]}}
        plan = plan_import("dest", bundle)
        assert plan.additions == [] and len(plan.collisions) == 1
        assert not plan.clean
        assert plan.collisions[0]["current_source"] == "human"

    def test_a_future_bundle_version_is_refused_not_best_effort_parsed(self):
        """A shape we do not understand, half-applied, is worse than one not applied."""
        plan = plan_import("c1", {"version": BUNDLE_VERSION + 1, "sections": {}})
        assert plan.refused and not plan.clean

    def test_malformed_entries_are_refused_individually(self):
        plan = plan_import("c1", {"version": BUNDLE_VERSION, "sections": {
            "synonyms": [{"subject_kind": "metric"}]}})
        assert plan.refused

    def test_a_bundle_is_stable_yaml(self):
        """Two exports of one state must be byte-comparable or the round-trip gate means
        nothing."""
        from aughor.ontology.vocabulary import add_synonym

        add_synonym("c1", "metric", "m", "b")
        add_synonym("c1", "metric", "m", "a")
        assert export_bundle("c1").to_yaml() == export_bundle("c1").to_yaml()

    def test_unparseable_yaml_reports_rather_than_raises(self):
        assert bundle_from_yaml("{{{ not yaml") is None
        assert bundle_from_yaml("version: 1") is None      # parses, but is not a bundle

    def test_a_valid_bundle_parses(self):
        text = export_bundle("c1").to_yaml()
        assert bundle_from_yaml(text) is not None
