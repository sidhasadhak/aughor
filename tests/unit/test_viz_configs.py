"""Per-chart display config for card-less surfaces (`viz_configs`).

A pinned card persists its display in `DashboardCard.render`. Charts that are NOT cards — a
findings-ledger row, a digest tile's detail, a KPI trend — had nowhere to put one, so every
edit (chart type, axes, colour binding, legend, transform, table/pivot view) died with the
component. Because the ledger is single-open, expanding a second row destroyed the first row's
edits *without a reload*.

Two properties matter here and both are easy to get wrong:
  * scope isolation — one schema's edits must never surface under another's
  * "reset to default" DELETES the row, so a later change to the default is picked up rather
    than shadowed by a stored copy of the old one
"""
from __future__ import annotations

import pytest

from aughor.dashboard.store import get_viz_configs, set_viz_config

BAR = {"type": "bar", "dim": "platform", "metric": "gmv"}
LINE = {"type": "line", "xTitle": "Month"}


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Never touch the real dashboard DB — the suite has emptied a live store before."""
    monkeypatch.setattr("aughor.dashboard.store._DB_PATH", str(tmp_path / "cards.db"))


def test_roundtrip_one_config():
    set_viz_config("workspace:netflix", "insight-1", "default", BAR)
    assert get_viz_configs("workspace:netflix", "default") == {"insight-1": BAR}


def test_update_overwrites_rather_than_duplicating():
    set_viz_config("workspace:netflix", "insight-1", "default", BAR)
    set_viz_config("workspace:netflix", "insight-1", "default", LINE)
    assert get_viz_configs("workspace:netflix", "default") == {"insight-1": LINE}


def test_scopes_are_isolated():
    """The whole point: a chart edited on one schema must not follow the user to another."""
    set_viz_config("workspace:netflix", "insight-1", "default", BAR)
    set_viz_config("workspace:luxexperience", "insight-1", "default", LINE)

    assert get_viz_configs("workspace:netflix", "default") == {"insight-1": BAR}
    assert get_viz_configs("workspace:luxexperience", "default") == {"insight-1": LINE}
    assert get_viz_configs("workspace:main", "default") == {}


def test_users_are_isolated():
    set_viz_config("workspace:netflix", "insight-1", "ana", BAR)
    assert get_viz_configs("workspace:netflix", "ana") == {"insight-1": BAR}
    assert get_viz_configs("workspace:netflix", "default") == {}


def test_empty_config_deletes_the_row():
    """"Back to default" must leave NO trace — otherwise the user is pinned to a snapshot of
    today's default and never sees an improved one."""
    set_viz_config("workspace:netflix", "insight-1", "default", BAR)
    set_viz_config("workspace:netflix", "insight-1", "default", {})
    assert get_viz_configs("workspace:netflix", "default") == {}


def test_reset_leaves_siblings_alone():
    set_viz_config("workspace:netflix", "insight-1", "default", BAR)
    set_viz_config("workspace:netflix", "insight-2", "default", LINE)
    set_viz_config("workspace:netflix", "insight-1", "default", {})
    assert get_viz_configs("workspace:netflix", "default") == {"insight-2": LINE}


def test_whole_scope_returns_in_one_call():
    """A brief renders many charts; the client fetches the scope once on mount."""
    for i in range(5):
        set_viz_config("workspace:netflix", f"insight-{i}", "default", {"type": "bar", "n": i})
    out = get_viz_configs("workspace:netflix", "default")
    assert len(out) == 5
    assert out["insight-3"]["n"] == 3


def test_unknown_scope_is_empty_not_an_error():
    assert get_viz_configs("workspace:nope", "default") == {}


def test_arbitrary_json_survives_the_roundtrip():
    """The config is opaque to the backend (like `render`) — the frontend owns the shape."""
    rich = {
        "view": "pivot", "type": "scatter", "refLines": [{"axis": "y", "value": 3.5, "label": "target"}],
        "colorField": "platform", "colorScale": "categorical", "tooltipOff": True,
    }
    set_viz_config("workspace:netflix", "insight-1", "default", rich)
    assert get_viz_configs("workspace:netflix", "default")["insight-1"] == rich
