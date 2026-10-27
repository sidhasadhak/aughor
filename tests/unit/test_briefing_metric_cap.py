"""Arc MC, MC-6 — the Briefing's cap a setting, read by area in the map's order (the user's call, 2026-10-26, §6 item
55(f): "Raise the default" — 24).

Off, the Briefing measures 12 in the income statement's order, exactly as before. On, it measures up to the workspace's
own number, else 24, ordered by the area each metric reads on — the statement's areas first — and a metric past the cap
still says the cap cut it. The falsifier: an approved metric under the cap left unmeasured as past it.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace as N

import pytest

from aughor.briefing import ranges
from aughor.kernel.flags import flag_overrides

FLAG = "briefing.metric_cap"


class _M:
    def __init__(self, name, label=""):
        self.name, self.label, self.status, self.connection = name, label or name.title(), "approved", "c"
        self.time_kind, self.tables, self.unit, self.sql, self.lineage = "flow", [], "", "", []
        self.time_source, self.time_confirmed_by = "rule", None


SPEC = ranges.RangeSpec(preset="custom", start=date(2026, 8, 1), end=date(2026, 9, 1),
                        previous_start=date(2026, 7, 1), previous_end=date(2026, 8, 1),
                        last_year_start=None, last_year_end=None, as_of=date(2026, 9, 15),
                        lag_days=8, lag_source="learned", still_moving=[], period="month")


@pytest.fixture
def retail(monkeypatch):
    from aughor.business_profile import metric_kb
    from aughor.semantic import metric_coverage
    monkeypatch.setattr(metric_kb, "industry_scope", lambda *a, **k: "retail")
    monkeypatch.setattr(metric_coverage, "tables_of", lambda *a, **k: [])


def _measure(monkeypatch, governed):
    from aughor.semantic import metric_time as mt
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: governed)
    monkeypatch.setattr(mt, "ensure_dates", lambda *a, **k: {})
    monkeypatch.setattr(mt, "declared", lambda m: True)
    monkeypatch.setattr(mt, "run_measure", lambda *a, **k: ([], "measured elsewhere"))
    return ranges.measure_range("c", SPEC, run_sql=lambda s: ([], [], ""), dialect="duckdb")


def test_off_the_briefing_measures_twelve_and_names_the_rest_past_its_cap(monkeypatch):
    out = _measure(monkeypatch, [_M(f"m{i}") for i in range(14)])
    cut = [u for u in out["unmeasured"] if "cap of 12" in u["reason"]]
    assert ranges.metric_cap("c") == 12 and len(cut) == 2


def test_on_it_measures_up_to_twenty_four_and_names_only_what_is_past_them(monkeypatch, retail):
    with flag_overrides({FLAG: True}):
        assert ranges.metric_cap("c") == 24
        out = _measure(monkeypatch, [_M(f"m{i}") for i in range(26)])
    reasons = [u["reason"] for u in out["unmeasured"]]
    assert sum("cap of 24" in r for r in reasons) == 2
    assert sum(r == "measured elsewhere" for r in reasons) == 24        # every one under the cap was read


def test_a_workspace_sets_its_own_cap(monkeypatch):
    from aughor.orgsettings import store as org_store
    monkeypatch.setattr(org_store, "effective_settings", lambda ws=None: N(briefing_metric_cap=6))
    with flag_overrides({FLAG: True}):
        assert ranges.metric_cap("c") == 6


def test_on_the_metrics_read_by_area_in_the_maps_order(monkeypatch, retail):
    governed = [_M("session_conversion_rate", "Session Conversion Rate"), _M("repeat_purchase_rate",
                                                                            "Repeat Purchase Rate"),
                _M("item_return_rate", "Item Return Rate"), _M("gmv", "GMV")]
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: governed)
    from aughor.briefing import reading_order as RO
    monkeypatch.setattr(RO, "industry_reading", lambda conn_id: ([], []))
    with flag_overrides({FLAG: True}):
        got = [m.name for m in ranges.governed_metrics("c")]
        areas = ranges.areas_of("c", governed)
    assert got == ["gmv", "item_return_rate", "session_conversion_rate", "repeat_purchase_rate"]
    assert areas["gmv"]["name"] == "Orders & sales" and areas["item_return_rate"]["id"] == "returns"
    # off, the statement's order holds and nothing is placed
    assert ranges.areas_of("c", governed) == {}
