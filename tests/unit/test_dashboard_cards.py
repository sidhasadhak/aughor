"""Unit tests for the dashboard-card store (Briefing cockpit, Slice 0 foundation).

Hermetic: conftest points AUGHOR_DASHBOARD_DB at a throwaway temp dir. Each test uses a
distinct connection_id / scope_ref so list-count assertions never see another test's rows.
"""
from __future__ import annotations

from aughor.dashboard.models import CardProvenance, CardRefresh, DashboardCard
from aughor.dashboard.store import (
    delete_card,
    get_card,
    list_cards,
    upsert_card,
)


def _card(**kw) -> DashboardCard:
    base = dict(
        connection_id="workspace",
        scope="canvas",
        scope_ref="canvas_a",
        source="insight",
        kind="kpi",
        title="Refund rate",
        sql="SELECT AVG(refunded) FROM orders",
    )
    base.update(kw)
    return DashboardCard(**base)


def test_upsert_assigns_id_and_timestamps():
    card = upsert_card(_card(connection_id="conn_ts"))
    assert card.id, "an id is assigned on first write"
    assert card.created_at and card.updated_at
    assert card.created_at == card.updated_at


def test_create_get_roundtrips_nested_fields():
    card = upsert_card(_card(
        connection_id="conn_rt",
        render={"chartType": "line", "chartConfig": {"x": "month", "y": "rate"}},
        refresh=CardRefresh(cadence="daily", last_value=4.2, prev_value=3.9),
        thresholds={"critical": 5.0, "direction": "above"},
        provenance=CardProvenance(insight_id="ins_9", receipt_ref="insight:workspace:ins_9"),
        links=["ins_9", "ins_12"],
    ))
    got = get_card(card.id)
    assert got is not None
    assert got.render == {"chartType": "line", "chartConfig": {"x": "month", "y": "rate"}}
    assert got.refresh.cadence == "daily"
    assert got.refresh.last_value == 4.2 and got.refresh.prev_value == 3.9
    assert got.thresholds == {"critical": 5.0, "direction": "above"}
    assert got.provenance.insight_id == "ins_9"
    assert got.provenance.receipt_ref == "insight:workspace:ins_9"
    assert got.links == ["ins_9", "ins_12"]
    assert got.sql == "SELECT AVG(refunded) FROM orders"


def test_update_preserves_created_at_and_bumps_updated_at():
    card = upsert_card(_card(connection_id="conn_upd", title="v1"))
    created = card.created_at
    updated = upsert_card(card.model_copy(update={"title": "v2"}))
    assert updated.id == card.id
    assert updated.title == "v2"
    assert updated.created_at == created            # created_at preserved
    assert updated.updated_at >= created            # updated_at bumped (>= for same-clock)
    assert get_card(card.id).title == "v2"


def test_list_filters_by_scope_and_scope_ref():
    upsert_card(_card(connection_id="conn_list", scope="canvas", scope_ref="cvA", title="a"))
    upsert_card(_card(connection_id="conn_list", scope="canvas", scope_ref="cvB", title="b"))
    upsert_card(_card(connection_id="conn_list", scope="workspace", scope_ref="wsA", title="c"))

    canvas_a = list_cards(connection_id="conn_list", scope="canvas", scope_ref="cvA")
    assert [c.title for c in canvas_a] == ["a"]

    all_canvas = list_cards(connection_id="conn_list", scope="canvas")
    assert {c.title for c in all_canvas} == {"a", "b"}

    everything = list_cards(connection_id="conn_list")
    assert {c.title for c in everything} == {"a", "b", "c"}


def test_note_card_has_body_no_sql():
    card = upsert_card(_card(
        connection_id="conn_note", kind="note", source="authored",
        title="Watch DACH margins", sql="", body="Gut feel: DACH is softening.",
    ))
    got = get_card(card.id)
    assert got.kind == "note"
    assert got.sql == ""
    assert got.body == "Gut feel: DACH is softening."


def test_delete_card():
    card = upsert_card(_card(connection_id="conn_del"))
    assert get_card(card.id) is not None
    assert delete_card(card.id) is True
    assert get_card(card.id) is None
    assert delete_card(card.id) is False           # idempotent: gone already


def test_model_defaults_are_sane():
    c = DashboardCard(connection_id="x", title="t")
    assert c.scope == "canvas"
    assert c.kind == "kpi"
    assert c.source == "authored"
    assert c.render == {} and c.links == []
    assert c.refresh.cadence == "brief_cycle"
    assert c.provenance.insight_id == ""
