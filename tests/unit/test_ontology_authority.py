"""The law that decides which definition wins when the warehouse disagrees with itself.

Ported from a warehouse vendor's context layer with one inversion, and this is where that
inversion is pinned: they rank competing definitions by AUTHORITY (source standing,
reliance, freshness). We can do something they never claim — EXECUTE the formula against
the live database — so verification is a TIER and authority is only a tiebreak within it.

The test that matters most is `test_verification_beats_every_authority_signal_at_once`:
popularity ranking gets that case wrong, confidently.
"""
from __future__ import annotations

from aughor.ontology.authority import authority, choose, rank
from aughor.ontology.models import DefinitionSource


def d(**kw) -> DefinitionSource:
    kw.setdefault("formula_sql", "SUM(x)")
    return DefinitionSource(**kw)


# ── verification is a tier, never a term in the score ────────────────────────────────

def test_verification_beats_every_authority_signal_at_once():
    """The failure popularity ranking cannot avoid, and the reason we inverted it.

    A wrong formula on the company's most-loved certified dashboard, relied on by forty
    teams, written today by a named author — against a correct formula nobody has opened.
    PageRank picks the popular wrong one and sounds confident.
    """
    popular = d(formula_sql="SUM(gross)", source_asset="Exec Revenue Dashboard",
                source_kind="dashboard", author="Priya", certified=True,
                use_count=400, recorded_at="2026-09-08T10:00:00Z", verified=False)
    checked = d(formula_sql="SUM(net)", source_asset="rpt_revenue",
                source_kind="table", author="", certified=False,
                use_count=0, recorded_at="2019-01-01T00:00:00Z", verified=True)

    assert rank([popular, checked])[0] is checked
    # ...and every authority signal genuinely favours the loser, so the tier did the work.
    assert authority(popular) > authority(checked)


def test_authority_orders_candidates_only_within_one_tier():
    weak = d(source_asset="a note", source_kind="manual", verified=True)
    strong = d(source_asset="nightly_rollup", source_kind="pipeline", certified=True,
               use_count=30, author="Sam", verified=True)
    assert rank([weak, strong])[0] is strong

    weak_u = d(source_asset="a note", source_kind="manual", verified=False)
    strong_u = d(source_asset="nightly_rollup", source_kind="pipeline", certified=True,
                 use_count=30, author="Sam", verified=False)
    assert rank([weak_u, strong_u])[0] is strong_u


def test_reliance_is_capped_so_popularity_cannot_swamp_everything_else():
    """400 uses is not 400x better than one. Uncapped, reliance eats every other signal."""
    beloved = d(source_asset="dash", source_kind="dashboard", use_count=4000)
    solid = d(source_asset="pipe", source_kind="pipeline", use_count=25, certified=True)
    assert rank([beloved, solid])[0] is solid


def test_an_unattributed_claim_is_weaker_but_still_a_claim():
    named = d(source_asset="same", source_kind="query", author="Ali")
    anon = d(source_asset="same", source_kind="query", author="")
    assert rank([anon, named])[0] is named


def test_an_unparseable_or_missing_date_sinks_rather_than_crashing():
    for bad in ("", "not a date", "2026-13-45"):
        assert rank([d(recorded_at=bad), d(recorded_at="2026-09-01T00:00:00Z")])[0] \
            .recorded_at == "2026-09-01T00:00:00Z"


def test_the_space_separated_timestamp_form_orders_correctly():
    """This field has carried both the ISO `T` and the space form; a lexical compare
    across the two mis-orders them, which this repo has already paid for once."""
    older = d(source_asset="old", recorded_at="2026-01-01 00:00:00")
    newer = d(source_asset="new", recorded_at="2026-09-01T00:00:00Z")
    assert rank([older, newer])[0].source_asset == "new"


# ── what the panel beside the answer says ────────────────────────────────────────────

def test_the_chosen_definition_names_its_asset_and_its_author():
    c = choose([d(source_asset="DAIS 2026 Sales Dashboard", author="Alejandro",
                  verified=True)])
    assert "DAIS 2026 Sales Dashboard" in c.why and "Alejandro" in c.why
    assert "verified against the live database" in c.why
    assert not c.contested


def test_an_unverified_winner_says_so_in_the_words_a_reader_needs():
    c = choose([d(source_asset="a dashboard", author="Sam", certified=True,
                  use_count=99, verified=False)])
    assert "NOTHING here is verified" in c.why and "not a checked one" in c.why


def test_a_disagreeing_runner_up_is_reported_as_a_dissent():
    c = choose([
        d(formula_sql="SUM(net)", source_asset="rpt_revenue", verified=True),
        d(formula_sql="SUM(gross)", source_asset="Exec Dashboard", author="Priya"),
    ])
    assert c.contested and c.dissenter is not None
    assert "Exec Dashboard" in c.why and "unverified" in c.why


def test_a_runner_up_that_AGREES_is_corroboration_not_a_conflict():
    c = choose([d(formula_sql="SUM(net)", source_asset="one", verified=True),
                d(formula_sql="SUM(net)", source_asset="two")])
    assert not c.contested and c.dissenter is None


def test_two_verified_formulas_that_disagree_are_escalated_not_papered_over():
    """Both run, and they differ: that is a real disagreement about the business, and no
    ranking should resolve it quietly."""
    c = choose([d(formula_sql="SUM(net)", source_asset="A", verified=True, certified=True),
                d(formula_sql="SUM(gross)", source_asset="B", verified=True)])
    assert c.contested
    assert "genuinely disagrees with itself" in c.why and "A person has to settle" in c.why


def test_definitions_with_no_formula_are_not_candidates():
    c = choose([d(formula_sql="   ", source_asset="empty", certified=True, use_count=99),
                d(formula_sql="SUM(x)", source_asset="real")])
    assert c.winner is not None and c.winner.source_asset == "real"


def test_no_definitions_is_an_honest_empty():
    c = choose([])
    assert c.winner is None and not c.contested
    assert "No definition has been recorded" in c.why


# ── the field is additive: every graph written before it still loads ─────────────────

def test_a_metric_written_before_this_field_loads_with_an_empty_list():
    from aughor.ontology.models import OntologyMetric
    m = OntologyMetric(id="revenue", display_name="Revenue", entity="orders",
                       formula_sql="SUM(net)")
    assert m.definitions == []
