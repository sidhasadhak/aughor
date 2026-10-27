"""Arc MC, MC-1 — the knowledge base as the map a connection's metrics cover (ROADMAP §3.62).

The user, 2026-10-26: *"I think we already this list of metrics per industry as knowledge base"* — about 130 curated
metric patterns, each with its template and traps, read only to answer a question and never to propose. Each now names
its area, its kind and its direction; each package declares its areas; an industry takes a function package's area into
its own. MC-1's falsifier: a metric pattern in no area, or an area the knowledge base lacks unsaid.
"""
from __future__ import annotations

import json

import pytest

from aughor.packs import knowledge
from aughor.semantic import metric_map as M


def _map_for(industry: str = "") -> M.MetricMap:
    pkgs = [p for p in knowledge.packages() if p.layer != "industry" or (industry and p.industry == industry)]
    return M.map_of(pkgs)


INDUSTRIES = sorted({p.industry for p in knowledge.packages() if p.layer == "industry"})


@pytest.mark.parametrize("industry", ["", *INDUSTRIES])
def test_every_metric_pattern_names_an_area_its_package_declares_and_a_kind(industry):
    mmap = _map_for(industry)
    assert mmap.problems == []
    for p in mmap.patterns():
        assert p.kind in (*M.KINDS, M.ANALYSIS), p.id
        assert p.direction in M.DIRECTIONS, p.id
        assert mmap.area(p.area) is not None, p.id


def test_every_metric_shaped_pattern_of_every_active_package_is_on_some_map():
    """Read from the files, not the map: a pattern the map silently dropped would pass the test above."""
    on_a_map = {p.id for industry in ["", *INDUSTRIES] for p in _map_for(industry).patterns()}
    in_files = set()
    for kb_file, data in knowledge.iter_kb_payloads():
        for entry in (data if isinstance(data, list) else [data]):
            if M.is_metric_pattern(entry):
                in_files.add(entry["id"])
                assert entry.get("area") and entry.get("kind") and entry.get("direction"), entry["id"]
    assert len(in_files) >= 120
    assert in_files <= on_a_map


def test_retail_reads_its_income_statement_first_then_the_operating_areas_then_the_function_areas_it_does_not_take():
    mmap = _map_for("retail")
    ids = [a.id for a in mmap.areas]
    assert ids[:5] == ["orders_sales", "returns", "margin_pricing", "fulfilment", "marketing"]
    assert ids.index("inventory") < ids.index("recurring_revenue") < ids.index(M.OTHER) == len(ids) - 1
    assert mmap.industry_pack == "retail"


def test_an_industry_takes_a_function_packages_area_into_its_own():
    mmap = _map_for("retail")
    returns = mmap.area("returns")
    assert {p.id for p in returns.patterns} >= {"ec_return_rate", "ec_refund_rate", "refund_rate"}
    refund = next(p for p in returns.patterns if p.id == "refund_rate")
    assert (refund.pack_id, refund.declared_area, refund.area) == ("finance", "refunds", "returns")
    assert mmap.area("refunds") is None                          # read under retail's own name
    assert "web" in mmap.area("traffic_conversion").words and "feature" not in mmap.area("traffic_conversion").words


def test_an_area_the_knowledge_base_has_no_pattern_for_is_still_on_the_map_and_readable():
    area = _map_for("retail").area("clienteling_events")
    assert area is not None and area.patterns == [] and area.readable


def test_a_recipe_carries_its_area_and_one_without_is_placed_by_its_name():
    retail = _map_for("retail")
    assert [r.name for r in retail.area("returns").recipes] == ["return_rate"]
    assert retail.area("returns").recipes[0].sane_range["max"] == 0.30
    airline = _map_for("airline")
    assert {r.name for r in airline.area("operations").recipes} == {"on_time_arrival_rate", "cancellation_rate",
                                                                       "completion_factor"}


def test_the_methods_only_area_is_not_readable_and_its_patterns_are_never_proposable():
    area = _map_for("retail").area("analysis")
    assert area is not None and not area.readable
    assert area.patterns and not area.proposable_patterns


def test_a_pattern_naming_an_area_its_package_does_not_declare_is_said_not_dropped(tmp_path, monkeypatch):
    pack = tmp_path / "packs" / "shop"
    (pack / "kb").mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: shop\nname: Shop\nversion: 1\nlayer: function\nstatus: active\n")
    (pack / "areas.yaml").write_text("areas:\n  - id: sales\n    name: Sales\n    words: [sale]\n")
    (pack / "kb" / "shop_kb.json").write_text(json.dumps([
        {"id": "shop_orders", "title": "Orders", "pattern_type": "metric", "area": "sales", "kind": "volume",
         "direction": "up"},
        {"id": "shop_ghost", "title": "Ghost", "pattern_type": "metric", "area": "nowhere", "kind": "value",
         "direction": "up"},
    ]))
    monkeypatch.setattr(knowledge, "pack_roots", lambda: [tmp_path / "packs"])
    knowledge.reset()
    try:
        mmap = M.map_of(list(knowledge.packages()))
    finally:
        monkeypatch.undo()
        knowledge.reset()
    assert [p.id for p in mmap.area("sales").patterns] == ["shop_orders"]
    assert mmap.problems == ["pattern shop_ghost (shop/kb/shop_kb.json) names area nowhere, which its package does "
                             "not declare"]


def test_words_place_by_the_longest_phrase_and_a_pattern_is_matched_word_for_word():
    retail = _map_for("retail")
    named = [a for a in retail.areas if not a.generic]
    assert [a.id for a, _ in M.best_areas("customer_service", named)] == ["service"]
    assert [a.id for a, _ in M.best_areas("web_events", named)] == ["traffic_conversion"]
    assert {a.id for a, _ in M.best_areas("return_logistics", named)} == {"returns", "fulfilment"}
    assert M.match_pattern("gmv", "GMV", retail.patterns()).id == "ec_gmv"
    assert M.match_pattern("clienteling_gmv_per_interaction", "Clienteling GMV per Interaction",
                           retail.patterns()) is None


def test_the_workspaces_airline_tables_are_each_placed_where_an_airline_reads_them():
    """2026-10-26, the user: "add the airline words" — on the workspace's main (re-profiled an airline), baggage,
    upgrades, crew, boarding passes and airports were placed in no area, and flights only under capacity, so on-time
    performance had no table to be written over."""
    from aughor.semantic.metric_coverage import TableFacts, place_table
    areas = _map_for("airline").readable
    placed = {t: {p.area for p in place_table(TableFacts(t), areas)}
              for t in ("baggage", "upgrades", "crew", "crew_assignments", "boarding_passes", "airports", "flights")}
    assert placed == {"baggage": {"unit_revenue"}, "upgrades": {"unit_revenue"}, "crew": {"operations"},
                      "crew_assignments": {"operations"}, "boarding_passes": {"operations"}, "airports": {"network"},
                      "flights": {"network", "operations"}}
