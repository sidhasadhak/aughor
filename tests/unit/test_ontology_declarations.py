"""Wave O6 — declared exclusions, honest coverage, and checked promises.

The carrying tests: :func:`test_a_probe_that_cannot_answer_is_unknown_never_fresh` ("we
checked and it holds" and "we could not check" are different facts, and collapsing them is
how a green board comes to mean nothing) and
:func:`test_an_excluded_table_leaves_the_denominator` (counting it as unmapped nags forever
about tables nobody will map, and a team that learns to ignore the number ignores the real
gaps in it).
"""
from __future__ import annotations

import pytest

from aughor.ontology.declarations import (
    EXCLUSION_REASONS,
    GREEN,
    ORANGE,
    RED,
    Declaration,
    Exclusion,
    caveats_for_tables,
    check_declaration,
    coverage,
    drift_report,
    exclusion_from,
    freshness_vocabulary,
)


def _decl(table="orders", kind="cardinality", expected="one_to_many") -> Declaration:
    return Declaration(table=table, kind=kind, expected=expected)


def _probe(ok: bool, observed: str = "one_to_one"):
    return lambda d: (observed, ok)


# ── coverage with declared exclusions ───────────────────────────────────────────────

def test_an_excluded_table_leaves_the_denominator():
    """Unmapped and out-of-scope look identical in a raw number, and treating them alike
    gives a green dashboard hiding real gaps AND endless nagging at once."""
    c = coverage(["orders", "items", "_migrations"], ["orders"],
                 [Exclusion("_migrations", "system_table")])
    assert c.in_scope == 2 and c.mapped == 1 and c.share == 0.5


def test_coverage_with_no_exclusions_is_the_plain_ratio():
    c = coverage(["a", "b", "c", "d"], ["a", "b"], [])
    assert c.share == 0.5 and c.excluded == 0


def test_an_excluded_table_that_was_mapped_anyway_still_counts_as_mapped():
    """An exclusion says 'not required', never 'not allowed'."""
    c = coverage(["a", "b"], ["a", "b"], [Exclusion("b", "deprecated")])
    assert c.mapped == 2 and c.excluded == 0 and c.share == 1.0


def test_bands():
    assert coverage(["a"] * 1, ["a"], []).band == GREEN
    assert coverage(list("abcde"), ["a", "b", "c"], []).band == ORANGE
    assert coverage(list("abcde"), ["a"], []).band == RED


def test_a_connection_with_nothing_in_scope_is_green_not_a_division_error():
    c = coverage(["_m"], [], [Exclusion("_m", "system_table")])
    assert c.in_scope == 0 and c.share == 1.0 and c.band == GREEN


def test_table_names_are_matched_bare():
    c = coverage(["shop.orders"], ["orders"], [])
    assert c.mapped == 1


def test_an_exclusion_needs_a_known_reason():
    """Free text makes coverage un-aggregatable; 'other' with a note beats a taxonomy
    nobody fits."""
    assert exclusion_from({"table": "t", "reason": "system_table"}) is not None
    assert exclusion_from({"table": "t", "reason": "because"}) is None
    assert exclusion_from({"table": "", "reason": "system_table"}) is None
    assert "other" in EXCLUSION_REASONS


# ── checked promises ────────────────────────────────────────────────────────────────

def test_a_holding_declaration_is_fresh():
    r = check_declaration(_decl(), _probe(True, "one_to_many"))
    assert r.state == "fresh" and not r.violated and r.caveat() == ""


def test_a_violated_declaration_is_dirty_and_carries_a_caveat():
    """Genie DOCUMENTS that a wrong cardinality silently corrupts. This CHECKS it."""
    r = check_declaration(_decl(), _probe(False, "one_to_one"))
    assert r.state == "dirty" and r.violated
    caveat = r.caveat()
    assert "orders" in caveat and "one_to_many" in caveat and "one_to_one" in caveat
    assert "may be wrong" in caveat


def test_a_probe_that_cannot_answer_is_unknown_never_fresh():
    """'We checked and it holds' and 'we could not check' are different facts. Collapsing
    them is how a green board comes to mean nothing — the same refusal N3 made when an
    unreadable ontology marked nothing stale."""
    def _boom(_d):
        raise RuntimeError("probe unavailable")

    r = check_declaration(_decl(), _boom)
    assert r.state == "unknown" and not r.violated
    assert r.caveat() == ""


def test_no_fifth_freshness_state():
    """C3 defined four, V lifted them platform-wide, N3 refused to add a fifth and added
    an orthogonal axis instead. O6 does the same."""
    assert freshness_vocabulary() == ("fresh", "dirty", "stale", "unknown")
    states = {check_declaration(_decl(), _probe(ok)).state for ok in (True, False)}
    assert states <= set(freshness_vocabulary())


@pytest.mark.parametrize("kind", ["cardinality", "grain", "active_filter"])
def test_every_declaration_kind_checks(kind):
    r = check_declaration(_decl(kind=kind), _probe(False))
    assert r.violated and kind in r.caveat()


# ── caveats ride the tables an answer touched ───────────────────────────────────────

def test_caveats_match_only_the_tables_in_play():
    results = [check_declaration(_decl("orders"), _probe(False)),
               check_declaration(_decl("returns"), _probe(False))]
    got = caveats_for_tables(results, ["orders"])
    assert len(got) == 1 and "orders" in got[0]


def test_holding_declarations_contribute_no_caveat():
    results = [check_declaration(_decl("orders"), _probe(True))]
    assert caveats_for_tables(results, ["orders"]) == []


def test_caveat_matching_normalises_qualified_names():
    results = [check_declaration(_decl("orders"), _probe(False))]
    assert caveats_for_tables(results, ["shop.orders"])


# ── the report ──────────────────────────────────────────────────────────────────────

def test_the_report_names_unchecked_declarations_separately():
    """Folding 'could not check' into 'fine' is the silent-success shape the L wave kept
    catching."""
    def _mixed(d):
        if d.table == "broken":
            raise RuntimeError("down")
        return ("x", d.table != "bad")

    rep = drift_report([_decl("ok"), _decl("bad"), _decl("broken")], _mixed)
    assert len(rep.violated) == 1 and len(rep.unknown) == 1
    summary = rep.summary()
    assert "1 violated" in summary and "1 could not be checked" in summary


def test_a_clean_report_does_not_mention_unchecked():
    rep = drift_report([_decl()], _probe(True))
    assert "could not" not in rep.summary()


def test_an_empty_report_says_so():
    assert "No declarations" in drift_report([], _probe(True)).summary()


def test_the_report_serializes():
    rep = drift_report([_decl()], _probe(False))
    out = rep.to_dict()
    assert out["violated"] and out["violated"][0]["caveat"]
