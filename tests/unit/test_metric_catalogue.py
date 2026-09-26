"""The metrics that apply to ONE connection: industry + explorer, deduped, honest about state.

Asked for 2026-09-18: the Semantic Layer's Metrics sub-tab must list, per connection, every
applicable metric — the industry chosen in Settings plus the explorer's own judgement —
editable on expand.

These pin the rules that make that list trustworthy rather than merely long:
  1. all three sources reach the list;
  2. precedence — an edited definition shadows the recipe it came from, once;
  3. an industry recipe whose roles are not bound says so and is NOT editable;
  4. materialising scopes the copy to the connection and lands it DRAFT, never approved;
  5. an unbindable recipe is refused rather than written as unexecutable SQL.
"""
import pytest

from aughor.semantic import metric_catalogue as MC


# ── doubles ───────────────────────────────────────────────────────────────────

class _Binds:
    def __init__(self, required): self.required = list(required)


class _PackMetric:
    def __init__(self, name, title="", formula="", required=(), unit="", definition=""):
        self.name, self.title, self.formula = name, title, formula
        self.binds = _Binds(required)
        self.unit, self.unit_or_range, self.definition = unit, "", definition
        self.grain, self.anti_patterns, self.sane_range = "", [], None


class _Pack:
    def __init__(self, metrics): self.metrics = list(metrics)


class _Pkg:
    def __init__(self, pack_id, layer="industry", industry="", directory="/x"):
        self.pack_id, self.layer, self.industry, self.directory = pack_id, layer, industry, directory
        self.name = pack_id


class _NSM:
    def __init__(self, name, maps_to="", value_sql="", why=""):
        self.name, self.maps_to, self.value_sql = name, maps_to, value_sql
        self.definition, self.unit_or_range, self.why_it_matters = "", "ratio 0-1", why


class _Profile:
    def __init__(self, metrics): self.north_star_metrics = list(metrics)


@pytest.fixture
def wired(monkeypatch):
    """A connection on the 'retail' industry with one bound pack role and one explorer metric."""
    state = {
        "defined": [],
        "packages": [_Pkg("retail", "industry", "retail")],
        "pack": _Pack([
            _PackMetric("gross_margin_rate", "Gross margin rate",
                        "SUM({{role.order.margin}})", required=["order"], unit="ratio"),
            _PackMetric("net_interest_margin", "Net interest margin",
                        "SUM({{role.financial_period.x}})", required=["financial_period"]),
        ]),
        # The shape the store actually writes: `columns` maps ATTRIBUTE -> column. The
        # singular `column` this used to carry was enough for `_bound_roles`, which reads
        # only the role keys — but materialise now resolves the formula through this map,
        # and a stub that does not look like the real record cannot catch a resolver bug.
        "bound": {"order": {"table": "order_items", "columns": {"margin": "margin"}}},
        "profile": _Profile([_NSM("Return Rate", "order_items.returned_at, order_items.id",
                                  "COUNT(returned_at)/COUNT(id)", "returns erode margin")]),
    }
    monkeypatch.setattr(MC, "_defined_entries", lambda c: list(state["defined"]))
    monkeypatch.setattr("aughor.business_profile.metric_kb.industry_scope",
                        lambda c, s=None, **k: "retail")
    monkeypatch.setattr("aughor.packs.knowledge.packages", lambda: tuple(state["packages"]))
    monkeypatch.setattr("aughor.packs.loader.load_pack", lambda d: state["pack"])
    monkeypatch.setattr("aughor.packs.bindings.load_binding",
                        lambda p, c, s="": {"bindings": dict(state["bound"])})
    monkeypatch.setattr("aughor.business_profile.store.load",
                        lambda c, s=None: state["profile"])
    return state


class TestEverySourceReaches:
    def test_industry_and_explorer_both_listed(self, wired):
        rows = MC.catalogue_for("c1")
        by = {r.name: r for r in rows}
        assert "gross_margin_rate" in by, "the industry recipe is missing"
        assert "return_rate" in by, "the explorer's judgement is missing"
        assert by["gross_margin_rate"].source == MC.SOURCE_INDUSTRY
        assert by["return_rate"].source == MC.SOURCE_EXPLORER

    def test_an_unknown_connection_is_empty_not_everything(self):
        assert MC.catalogue_for("") == []

    def test_only_this_industry_s_package(self, wired, monkeypatch):
        """A banking recipe must not appear on a retail connection."""
        wired["packages"] = [_Pkg("banking", "industry", "banking")]
        assert [r for r in MC.catalogue_for("c1") if r.source == MC.SOURCE_INDUSTRY] == []

    def test_function_packages_apply_to_every_industry(self, wired):
        wired["packages"] = [_Pkg("finance", "function", "")]
        assert any(r.source == MC.SOURCE_INDUSTRY for r in MC.catalogue_for("c1"))


class TestBindingHonesty:
    def test_an_unbound_recipe_says_so(self, wired):
        row = {r.name: r for r in MC.catalogue_for("c1")}["net_interest_margin"]
        assert row.state == MC.STATE_NEEDS_BINDING
        assert row.missing_roles == ["financial_period"]
        assert row.editable is False, "an unbindable recipe must not look editable"

    def test_a_bound_recipe_is_proposed_never_approved(self, wired):
        row = {r.name: r for r in MC.catalogue_for("c1")}["gross_margin_rate"]
        assert row.state == MC.STATE_PROPOSED
        assert row.status != "approved"

    def test_no_binding_record_means_nothing_is_bound(self, wired, monkeypatch):
        monkeypatch.setattr("aughor.packs.bindings.load_binding", lambda p, c, s="": None)
        states = {r.name: r.state for r in MC.catalogue_for("c1")}
        assert states["gross_margin_rate"] == MC.STATE_NEEDS_BINDING


class TestFormulaHonesty:
    """18 of 77 stored north-star metrics (measured 2026-09-18) carry no `value_sql`."""

    def test_an_explorer_metric_without_a_formula_says_so(self, wired):
        wired["profile"] = _Profile([_NSM("Return Rate", "order_items.id", value_sql="")])
        row = {r.name: r for r in MC.catalogue_for("c1")}["return_rate"]
        assert row.state == MC.STATE_NEEDS_FORMULA

    def test_one_with_a_formula_is_proposed(self, wired):
        row = {r.name: r for r in MC.catalogue_for("c1")}["return_rate"]
        assert row.state == MC.STATE_PROPOSED

    def test_it_can_still_be_materialised(self, wired, monkeypatch):
        """Supplying the formula IS the edit — refusing here would leave the row that most
        needs editing as the only one that cannot be."""
        wired["profile"] = _Profile([_NSM("Return Rate", "order_items.id", value_sql="")])
        saved = {}
        monkeypatch.setattr("aughor.semantic.metrics.save_metric",
                            lambda m, *a, **k: saved.update(m.model_dump()))
        MC.materialise("c1", "return_rate")
        assert saved["sql"] == "" and saved["status"] == "draft"


class TestPrecedence:
    def test_a_definition_shadows_its_recipe_once(self, wired):
        wired["defined"] = [MC.CatalogueEntry(
            name="gross_margin_rate", label="Gross margin rate (ours)",
            source=MC.SOURCE_DEFINED, state=MC.STATE_DEFINED, sql="SUM(m)/SUM(r)",
            editable=True)]
        rows = [r for r in MC.catalogue_for("c1")
                if MC.normalize_name(r.name) == "gross_margin_rate"]
        assert len(rows) == 1, "the recipe and its override were both listed"
        assert rows[0].source == MC.SOURCE_DEFINED and rows[0].editable

    def test_names_collide_across_sources_after_normalising(self, wired):
        """'Gross Merchandise Value (GMV)' and 'gross_merchandise_value_gmv' are one metric."""
        wired["profile"] = _Profile([_NSM("Gross Margin Rate", "t.c")])
        rows = [r for r in MC.catalogue_for("c1")
                if MC.normalize_name(r.name) == "gross_margin_rate"]
        assert len(rows) == 1 and rows[0].source == MC.SOURCE_INDUSTRY


class TestMaterialise:
    def test_it_scopes_to_the_connection_and_lands_draft(self, wired, monkeypatch):
        saved = {}
        monkeypatch.setattr("aughor.semantic.metrics.save_metric",
                            lambda m, *a, **k: saved.update(m.model_dump()))
        m = MC.materialise("c1", "gross_margin_rate", actor="amit")
        assert saved["connection"] == "c1", "a copy must not overwrite the global definition"
        assert saved["status"] == "draft", "never approved — law 2 holds KPI sends on that"
        assert saved["version"] == 0 and not saved.get("approved_by")
        # RESOLVED, not copied. This asserted `SUM({{role.order.margin}})` — the pack's
        # formula stored verbatim — which is a governed definition nobody can run. The
        # copy exists to be edited and executed, so it carries the column this connection
        # bound. (Bare, not quoted: a double-quoted identifier is a STRING on BigQuery.)
        # …and, since 2026-09-26, as a STATEMENT: the bound formula wrapped over its table,
        # so what the editor opens on is what will run.
        assert saved["sql"].startswith("SELECT (SUM(margin)) AS gross_margin_rate")
        assert "{{role" not in saved["sql"]
        assert m.name == "gross_margin_rate"

    def test_it_refuses_an_unbindable_recipe(self, wired, monkeypatch):
        monkeypatch.setattr("aughor.semantic.metrics.save_metric",
                            lambda *a, **k: pytest.fail("must not write an unexecutable definition"))
        with pytest.raises(MC.MaterialiseError) as e:
            MC.materialise("c1", "net_interest_margin")
        assert "financial_period" in str(e.value)

    def test_it_refuses_an_unknown_metric(self, wired):
        with pytest.raises(MC.MaterialiseError):
            MC.materialise("c1", "no_such_metric")

    def test_the_explorer_metric_carries_its_provenance(self, wired, monkeypatch):
        saved = {}
        monkeypatch.setattr("aughor.semantic.metrics.save_metric",
                            lambda m, *a, **k: saved.update(m.model_dump()))
        MC.materialise("c1", "return_rate")
        assert saved["lineage"] == ["explorer"], "a reader must see where the formula came from"
