"""Cut-level knowledge frontier — the explorer's "what do I already know" map.

Pinned to the real symptom: the explorer re-asked cuts it had already covered
because coverage was tracked at coarse angle granularity, not at the level of
concrete measure×dimension cells. The frontier must (a) read covered cells out of
executed SQL, (b) subtract them from the universe of valuable cells, and (c) hand
back the uncovered ones ranked so the generator gets a concrete target.
"""
from aughor.explorer.frontier import (
    Cut, insight_cuts, covered_cuts, build_universe, rank_frontier, render_frontier_block,
)

# Real Phase-8 shapes.
REV_BY_REGION = "SELECT region, SUM(revenue) AS rev FROM missimi.orders GROUP BY region"
REV_BY_CHANNEL = ("SELECT marketing_channel, SUM(revenue) AS rev, "
                  "ROUND(SUM(revenue)*100.0/SUM(SUM(revenue)) OVER (),1) AS pct "
                  "FROM missimi.orders GROUP BY marketing_channel")
HEADLINE_AOV = "SELECT SUM(revenue)/NULLIF(COUNT(DISTINCT order_id),0) AS aov FROM missimi.orders"


class TestInsightCuts:
    def test_grouped_measure_yields_measure_by_dimension(self):
        assert insight_cuts(REV_BY_REGION) == {Cut("revenue", "region")}

    def test_window_pct_wrapper_does_not_add_a_cut(self):
        # the pct-of-total window must not register as a second measure/cut.
        # query_signature normalises column names (strips '_'), so the dimension
        # is the normalised "marketingchannel" — matching is on Cut.key() anyway.
        cuts = insight_cuts(REV_BY_CHANNEL)
        assert len(cuts) == 1
        assert next(iter(cuts)).key() == Cut("revenue", "marketing_channel").key()

    def test_ungrouped_is_headline_cut(self):
        cuts = insight_cuts(HEADLINE_AOV)
        assert Cut("revenue", "") in cuts            # SUM(revenue) headline
        assert all(c.dimension == "" for c in cuts)  # nothing grouped

    def test_unparseable_sql_advances_nothing(self):
        assert insight_cuts("not sql at all }{") == set()


class TestFrontier:
    def test_covered_subtracted_from_universe(self):
        insights = [{"sql": REV_BY_REGION}, {"sql": REV_BY_CHANNEL}]
        covered = covered_cuts(insights)
        universe = build_universe(
            measures=["revenue", "margin"],
            dimensions=["region", "marketing_channel", "category"],
        )
        frontier = rank_frontier(universe, covered)
        # the two covered cells are gone…
        assert Cut("revenue", "region") not in frontier
        assert Cut("revenue", "marketing_channel") not in frontier
        # …but uncovered cells remain (margin entirely, revenue×category)
        assert Cut("revenue", "category") in frontier
        assert Cut("margin", "region") in frontier

    def test_priority_measures_rank_first(self):
        universe = build_universe(measures=["revenue", "margin"], dimensions=["region"])
        ranked = rank_frontier(universe, set(), priority_measures=["margin"])
        assert ranked[0].measure == "margin"          # north-star measure leads

    def test_dimensional_cut_outranks_headline(self):
        universe = build_universe(measures=["revenue"], dimensions=["region"])
        ranked = rank_frontier(universe, set())
        assert ranked[0] == Cut("revenue", "region")  # a cut before the bare headline

    def test_render_block_empty_when_exhausted(self):
        assert render_frontier_block([]) == ""

    def test_render_block_names_concrete_cuts(self):
        block = render_frontier_block([Cut("margin", "category"), Cut("revenue", "")])
        assert "margin by category" in block
        assert "revenue (headline)" in block
