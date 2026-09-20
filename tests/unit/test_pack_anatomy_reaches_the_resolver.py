"""IP — the typed recipes reach the two resolvers that pick and recognise metrics.

Slice 2 put a package's metric recipes in the PROMPT. Two other readers resolve a metric
against `kb["metrics"]` and were still reading the prose list alone:

- `resolve_recipes` (via `match_metric`) picks the recipe for each north-star metric, and falls
  back to a per-metric LLM call when nothing matches;
- `metric_vocabulary` builds the token set `explorer.metric_coherence` recognises metrics by.

The measured consequence was worse than a miss. On airline, `match_metric` over the prose list
answered "completion factor" with the **Cancellation Rate** recipe — its token-overlap fallback
finding a wrong metric rather than none. A wrong formula and a wrong band, silently.
"""
from __future__ import annotations

from aughor.business_profile.metric_kb import (_norm, curated_kb, curated_metrics, match_industry,
                                               match_metric, metric_vocabulary, resolve_recipes)


def _tokens(metrics) -> set[str]:
    out = set()
    for m in metrics:
        for t in [m.get("name", ""), *(m.get("aliases") or [])]:
            if _norm(t):
                out.add(_norm(t))
    return out


class TestRecipeResolution:
    def test_completion_factor_no_longer_resolves_to_the_cancellation_recipe(self):
        """The bug this slice closes, named. Not "it now matches" — it matched before, wrongly."""
        prose = match_industry("airline") or {}
        assert (match_metric(prose, "completion factor") or {}).get("name") == "Cancellation Rate", \
            "fixture drift: the wrong-match this test exists for is gone"
        after = match_metric(curated_kb("airline"), "completion factor") or {}
        assert after.get("name") == "Completion factor", after.get("name")
        assert after.get("sourced") is True

    def test_resolve_recipes_itself_returns_the_verified_recipe(self):
        """Exercises the CALLER, not just `curated_kb`. Found by mutation: reverting
        `resolve_recipes` to the prose KB broke nothing, because every test stopped at the
        helper. No model call happens here — `_llm_fallback_recipes` runs only for a metric
        the KB does not cover, and this one is covered by construction."""
        class _Metric:
            def __init__(self, name): self.name = name

        class _Profile:
            industry = "airline"
            north_star_metrics = [_Metric("completion factor")]

        recipes = resolve_recipes(_Profile(), schema="")
        assert len(recipes) == 1, recipes
        assert recipes[0]["metric"] == "Completion factor", recipes[0]["metric"]
        assert "0.9505" in str(recipes[0]["sane_range"]), recipes[0]["sane_range"]
        assert recipes[0]["source"] != "llm-fallback"

    def test_the_verified_band_wins_over_the_prose_one(self):
        after = match_metric(curated_kb("airline"), "cancellation rate") or {}
        assert "0.0025" in str(after.get("sane_range")), after.get("sane_range")

    def test_curated_kb_is_empty_for_an_industry_we_do_not_carry(self):
        assert curated_kb("not-an-industry-we-carry") == {}

    def test_curated_kb_does_not_mutate_the_shared_industry_json(self):
        """`match_industry` hands back a shared, cached object. Replacing its metric list in
        place would leak the merge into every other reader of that dict."""
        before = len((match_industry("airline") or {}).get("metrics") or [])
        curated_kb("airline")
        assert len((match_industry("airline") or {}).get("metrics") or []) == before


class TestVocabulary:
    def test_the_packages_metrics_are_recognisable(self):
        vocab = {t for (t, _label, _formula) in metric_vocabulary("airline")}
        assert _norm("completion factor") in vocab
        assert _norm("on-time arrival rate") in vocab

    def test_the_vocabulary_never_narrows(self):
        """The regression this slice nearly shipped. Replacing "On-Time Performance (OTP)" with
        the typed `on_time_arrival_rate` outright dropped "punctuality", "on-time departure" and
        "on-time performance otp" — a silent narrowing inside a change meant to widen. The typed
        recipe inherits the names of the prose entry it replaces."""
        prose = _tokens((match_industry("airline") or {}).get("metrics") or [])
        merged = _tokens(curated_metrics("airline"))
        assert prose - merged == set(), f"recognition lost: {sorted(prose - merged)}"
        assert merged > prose

    def test_a_token_only_the_package_carries_is_recognised(self):
        """Found by mutation: reverting the vocabulary to the prose list broke nothing, because
        every token asserted ("completion factor", "on-time arrival rate", "punctuality") is
        ALSO a prose alias. These three exist only in `metrics/*.yaml`."""
        vocab = {t for (t, _label, _formula) in metric_vocabulary("airline")}
        for only_typed in ("schedule completion", "flights completed share", "cancelled flights share"):
            assert _norm(only_typed) in vocab, only_typed

    def test_the_kb_alone_view_really_excludes_the_package(self):
        """`include_packages=False` exists so `test_ip1_package_parity` can keep asking the
        question its (unre-measurable) fixture measured. If it ever silently returned the merged
        view, that fixture would stop guarding the move — so pin the difference here too."""
        merged = {t for (t, _l, _f) in metric_vocabulary("airline")}
        kb_only = {t for (t, _l, _f) in metric_vocabulary("airline", include_packages=False)}
        assert kb_only < merged
        assert _norm("schedule completion") in merged
        assert _norm("schedule completion") not in kb_only

    def test_punctuality_still_names_a_metric(self):
        vocab = {t for (t, _label, _formula) in metric_vocabulary("airline")}
        assert _norm("punctuality") in vocab

    def test_an_inherited_name_resolves_to_the_verified_recipe(self):
        hit = match_metric(curated_kb("airline"), "punctuality") or {}
        assert hit.get("sourced") is True, hit.get("name")


class TestInheritanceIsBounded:
    def test_an_uncovered_prose_metric_is_kept_whole(self):
        """Load Factor has no typed counterpart; it must survive untouched, not be absorbed."""
        merged = curated_metrics("airline")
        load = [m for m in merged if m.get("name") == "Load Factor"]
        assert load and not load[0].get("sourced")

    def test_inheritance_never_steals_a_name_another_typed_recipe_owns(self):
        """The defect the fix introduced, and the guard for it. Prose "Cancellation Rate" lists
        "completion factor" among its aliases — they are complements — so unguarded inheritance
        gave the cancellation recipe the completion-factor NAME, and it won the match because
        `match_metric` returns the first containment hit and typed recipes are ordered first."""
        by_name = {m["name"]: m for m in curated_metrics("airline")}
        cancellation = by_name["Cancellation rate"]
        assert _norm("completion factor") not in {_norm(a) for a in cancellation["aliases"]}, \
            cancellation["aliases"]
        assert (match_metric(curated_kb("airline"), "completion factor") or {}).get("name") \
            == "Completion factor"

    def test_no_metric_is_duplicated_after_inheritance(self):
        names = [m["name"] for m in curated_metrics("airline")]
        assert len(names) == len(set(names)), names
