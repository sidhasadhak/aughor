"""IP — a package's TYPED metric recipes reach the prompt, and outrank the prose ones.

The curated-metrics block in `explorer.agent` read `industry.json` alone. Airline shows the
cost: `cancellation_rate` is in both places. `industry.json` offers a prose band written by
whoever authored the file; `packs/airline/metrics/cancellation_rate.yaml` carries
`min: 0.0025, max: 0.0495` with the BTS publication it came from, and gate 4 reproduces those
figures on a 638,649-flight file. The model was shown the prose one and never the measured one.

These tests pin the four properties: the typed recipes arrive, they REPLACE the prose entry for
the same metric, they keep their basis (a band without its population is a rule of thumb), and a
package belonging to another industry cannot leak in.
"""
from __future__ import annotations

from aughor.business_profile.metric_kb import (_metric_key, _render_sane_range, curated_metrics,
                                               match_industry)


class TestTheTypedRecipesArrive:
    def test_airlines_package_metrics_are_in_the_curated_view(self):
        names = {m["name"] for m in curated_metrics("airline")}
        assert "Completion factor" in names, names
        assert "On-time arrival rate" in names, names

    def test_typed_recipes_come_first_so_truncation_cannot_drop_them(self):
        """The renderer takes `[:10]`. A published band must not be the thing that falls off."""
        merged = curated_metrics("airline")
        sourced = [i for i, m in enumerate(merged) if m.get("sourced")]
        prose = [i for i, m in enumerate(merged) if not m.get("sourced")]
        assert sourced and prose, merged
        assert max(sourced) < min(prose), [m["name"] for m in merged]


class TestTheTypedOneReplacesTheProseOne:
    def test_cancellation_rate_appears_once_and_is_the_published_one(self):
        merged = curated_metrics("airline")
        hits = [m for m in merged if _metric_key(m["name"]) == "cancellation rate"]
        assert len(hits) == 1, [m["name"] for m in merged]
        assert hits[0].get("sourced") is True
        # The measured band, not the prose one.
        assert "0.0025" in hits[0]["sane_range"], hits[0]["sane_range"]

    def test_the_prose_entry_for_a_covered_metric_is_dropped_not_appended(self):
        prose_names = {_metric_key(m.get("name")) for m in (match_industry("airline") or {}).get("metrics", [])}
        merged = curated_metrics("airline")
        assert "cancellation rate" in prose_names, "fixture drift: the prose metric is gone"
        assert len(merged) < len(prose_names) + 3, \
            f"a covered metric was appended rather than replaced: {[m['name'] for m in merged]}"


class TestABandKeepsItsBasis:
    def test_a_published_band_carries_the_population_it_was_published_for(self):
        hits = [m for m in curated_metrics("airline") if m.get("sourced")]
        assert hits
        # A band with no basis reads as a rule of thumb; the whole point is that it is not one.
        assert any("2019" in m["sane_range"] for m in hits), [m["sane_range"] for m in hits]

    def test_render_handles_a_typed_band(self):
        out = _render_sane_range({"min": 0.1, "max": 0.9, "basis": "what was published", "sources": ["x"]})
        assert out == "0.1–0.9 (what was published)"

    def test_render_passes_a_prose_band_through_unchanged(self):
        assert _render_sane_range("ratio 0..1; typically 0.75–0.90") == "ratio 0..1; typically 0.75–0.90"

    def test_render_handles_a_one_sided_band(self):
        assert _render_sane_range({"min": 0.2}) == "at least 0.2"
        assert _render_sane_range({"max": 3.0}) == "at most 3.0"

    def test_a_band_with_no_sources_is_not_marked_published(self):
        """The marker is a provenance claim. `metrics/*.yaml` is readable on a pack that never
        declared `anatomy: 1`, so gate 3's no-unsourced-band rule is not what guarantees this."""
        from aughor.business_profile.metric_kb import _anatomy_metrics
        from aughor.packs.models import PackMetric, SaneRange

        unsourced = PackMetric(name="m", sane_range=SaneRange(min=0.0, max=1.0, basis="a guess"))
        sourced = PackMetric(name="m", sane_range=SaneRange(min=0.0, max=1.0, basis="b", sources=["s"]))

        class _Pack:
            def __init__(self, metrics): self.metrics = metrics

            def dump(self): return None
        seen = []
        import aughor.packs.loader as loader
        import aughor.packs.knowledge as knowledge
        real_load, real_index = loader.load_pack, knowledge.knowledge_index

        class _Pkg:
            pack_id, industry, directory = "t", "airline", "/tmp/t"

        class _Idx:
            packages = (_Pkg(),)
        try:
            knowledge.knowledge_index = lambda: _Idx()
            for metric, expected in ((unsourced, False), (sourced, True)):
                loader.load_pack = lambda _d, _m=metric: _Pack([_m])
                seen.append(_anatomy_metrics("airline")[0]["sourced"] is expected)
        finally:
            loader.load_pack, knowledge.knowledge_index = real_load, real_index
        assert all(seen), seen

    def test_render_of_nothing_is_empty_not_the_word_none(self):
        assert _render_sane_range(None) == ""
        assert _render_sane_range({}) == ""


class TestScoping:
    def test_another_industrys_package_does_not_leak_in(self):
        """`saas` carries no `metrics/*.yaml`, so its curated view must carry no published band.
        Without the industry filter airline's three would appear on every industry.

        Measured while writing this: `packs/retail` DOES carry recipes (and no `anatomy: 1`),
        which is why the assertion names airline's metrics rather than just counting."""
        names = {m["name"] for m in curated_metrics("saas")}
        assert "Cancellation rate" not in names, names
        assert "On-time arrival rate" not in names, names
        assert not [m for m in curated_metrics("saas") if m.get("sourced")], names

    def test_a_pack_that_never_declared_anatomy_still_contributes(self):
        """`packs/retail` carries `metrics/*.yaml` with `anatomy: 0`. Reading recipes is not
        gated on the anatomy flag — the flag selects what gate 3 checks statically — and the
        existing Metrics-tab reader (`metric_catalogue._industry_entries`) reads them the same
        way. Pinned so nobody "fixes" this into an anatomy-only read."""
        sourced = {m["name"] for m in curated_metrics("retail") if m.get("sourced")}
        assert "Return rate" in sourced, sourced

    def test_an_unknown_industry_returns_nothing_rather_than_everything(self):
        assert curated_metrics("not-an-industry-we-carry") == []

    def test_a_draft_package_contributes_no_recipe(self):
        """`packs/banking` ships `status: draft`. Gate 6 says no agent reads it until a person
        activates it, and sourcing through the knowledge index honours that by construction."""
        for industry in ("banking", "lending"):
            assert not [m for m in curated_metrics(industry) if m.get("sourced")]


class TestMetricKey:
    def test_the_three_spellings_of_one_metric_agree(self):
        assert _metric_key("Cancellation Rate") == _metric_key("cancellation_rate") == "cancellation rate"

    def test_distinct_metrics_stay_distinct(self):
        assert _metric_key("Load Factor") != _metric_key("Completion factor")
