"""A Briefing signed and dated as a delivery (ROADMAP §6 item 42c): each send that left names the
version it delivered, and that version — not today's — is what the delivery opens to."""
from __future__ import annotations

from types import SimpleNamespace

from aughor.briefing import deliveries as D
from aughor.briefing import delivery as sender
from aughor.briefing import versions as V


def _briefing(revenue: float, narrative: str) -> dict:
    return {"narrative": narrative,
            "period": {"period": "week", "label": "Weekly", "covers": "2026-09-21 to 2026-09-27",
                       "measured": [{"name": "Revenue", "metric": "revenue", "current": revenue, "previous": 90.0,
                                     "unit": "USD", "status": "final"}], "unmeasured": []}}


def _kept(conn: str, briefing: dict, scope_key: str) -> dict:
    period = briefing["period"]
    stamp = V.record(conn, briefing, scope_key=scope_key, range_key=period["covers"], recipe=period["period"])
    return {**briefing, "version": stamp}


def test_a_delivery_names_the_version_that_left_and_opens_to_it_after_a_restatement():
    conn, scope = "dlv1", "dlv1:shop"
    first = _kept(conn, _briefing(100.0, "Revenue rose to 100."), scope)
    assert first["version"]["version"] == 1 and first["version"]["artifact_id"]
    sent = D.record_delivery(conn_id=conn, scope_key=scope, briefing=first, to="#ask_aughor as Aughor", to_kind="slack",
                             subscription_id="s1", subscription_name="Weekly to leadership", departure_id="dep-1",
                             receipt_line="Receipt dep-1", held_lines=2, now="2026-09-28T09:00:00+00:00")
    assert sent

    listed = D.deliveries_of(conn, first, scope_key=scope)
    [row] = listed["deliveries"]
    assert (row["version"], row["to"], row["departure_id"], row["restated_since"]) == (1, "#ask_aughor as Aughor", "dep-1", False)
    assert listed["current_version"] == 1 and row["held_lines"] == 2

    # the figures move: the Briefing is restated, and a second send delivers the new version
    second = _kept(conn, _briefing(140.0, "Revenue rose to 140."), scope)
    assert second["version"]["version"] == 2
    D.record_delivery(conn_id=conn, scope_key=scope, briefing=second, to="Leadership webhook", to_kind="trigger",
                      departure_id="dep-2", now="2026-09-29T09:00:00+00:00")
    listed = D.deliveries_of(conn, second, scope_key=scope)
    assert [(r["version"], r["restated_since"]) for r in listed["deliveries"]] == [(2, False), (1, True)]

    opened = D.delivery(sent)
    assert opened["briefing"]["narrative"] == "Revenue rose to 100."          # as sent, not as it stands
    assert opened["version"] == 1 and opened["current_version"] == 2 and opened["restated_since"] is True
    assert opened["connection_id"] == conn and opened["receipt_line"] == "Receipt dep-1"
    assert D.delivery("no-such-id") is None and D.delivery(first["version"]["artifact_id"]) is None   # a version is not a delivery


def test_a_briefing_with_no_kept_version_books_no_delivery_and_another_scope_lists_none():
    standing = {"narrative": "What we know.", "period": None}
    assert D.record_delivery(conn_id="dlv2", scope_key="dlv2", briefing=standing, to="x", to_kind="slack") == ""
    kept = _kept("dlv2", _briefing(5.0, "Five."), "dlv2")
    D.record_delivery(conn_id="dlv2", scope_key="dlv2", briefing=kept, to="#c", to_kind="slack", departure_id="d")
    assert len(D.deliveries_of("dlv2", kept, scope_key="dlv2")["deliveries"]) == 1
    assert D.deliveries_of("dlv2", kept, scope_key="dlv2:other")["deliveries"] == []


def test_only_a_send_that_left_is_booked():
    kept = _kept("dlv3", _briefing(7.0, "Seven."), "dlv3")
    sub = SimpleNamespace(id="s9", name="Daily", conn_id="dlv3", schema_name="")
    verdict = SimpleNamespace(record_id="dep-9", receipt_line=lambda: "Receipt dep-9")
    built = {"brief": kept, "held_lines": []}
    for status in ("held", "failed"):
        result = {"status": status}
        sender._book_delivery(sub, built, verdict, result, to="#c", to_kind="slack")
        assert "delivery_id" not in result
    assert D.deliveries_of("dlv3", kept, scope_key="dlv3")["deliveries"] == []
    result = {"status": "ok"}
    sender._book_delivery(sub, built, verdict, result, to="#c", to_kind="slack")
    assert result["delivery_id"]
    [row] = D.deliveries_of("dlv3", kept, scope_key="dlv3")["deliveries"]
    assert row["subscription_name"] == "Daily" and row["receipt_line"] == "Receipt dep-9"
