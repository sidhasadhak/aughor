"""DATA-06 depth — extend tenant enforcement past connections/investigations to the
monitors, alerts, brief-subscription and canvas surfaces, and org-bind the schedulers.

Every one of these resources keys by ``conn_id`` and carries no ``org_id`` of its own,
so its tenant is its connection's org. With ``AUGHOR_REQUIRE_IDENTITY`` on:
  * a by-id route (monitor/alert/subscription) 403s for the wrong org,
  * a list/read route surfaces only the caller's org,
  * creating one against another org's connection 403s,
  * localhost mode (flag off) stays byte-identical (no filtering, no 403).

Cross-org requests assert *only* on the 403 status (never which layer produced it):
with RBAC also active a fresh org's first caller bootstraps to owner and is stopped by
the object-level owner-check, but either the RBAC gate or the owner-check yields 403 —
the test is robust to which fires first. Unique org ids per test avoid shared RBAC state.
"""
from __future__ import annotations

from aughor.util.time import now_iso_z


def _mk_conn(org: str, name: str) -> str:
    from aughor.db import registry
    from aughor.org.context import using_org
    with using_org(org):
        return registry.add_connection(name, "duckdb", "data/aughor.duckdb")


def _mk_monitor(conn_id: str, name: str = "mon"):
    from aughor.monitors.models import Monitor
    from aughor.monitors.store import upsert_monitor
    return upsert_monitor(Monitor(conn_id=conn_id, name=name))


def _mk_alert(conn_id: str, monitor_id: str):
    from aughor.monitors.models import MonitorAlert
    from aughor.monitors.store import append_alert
    return append_alert(MonitorAlert(monitor_id=monitor_id, conn_id=conn_id, triggered_at=now_iso_z()))


def _mk_subscription(conn_id: str, name: str = "sub"):
    from aughor.briefs.models import BriefSubscription
    from aughor.briefs.store import save_subscription
    return save_subscription(BriefSubscription(conn_id=conn_id, name=name, trigger_id="t-x"))


# ── Monitors ─────────────────────────────────────────────────────────────────────

def test_monitor_by_id_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.monitors.store import delete_monitor

    cid = _mk_conn("d6mon_a", "mon-a-conn")
    mon = _mk_monitor(cid)
    try:
        # wrong org cannot read the monitor by id
        assert client.get(f"/monitors/{mon.id}", headers={"X-Aughor-Org": "d6mon_b"}).status_code == 403
        # owner can
        assert client.get(f"/monitors/{mon.id}", headers={"X-Aughor-Org": "d6mon_a"}).status_code == 200
        # wrong org cannot delete it; owner can
        assert client.delete(f"/monitors/{mon.id}", headers={"X-Aughor-Org": "d6mon_b"}).status_code == 403
        assert client.delete(f"/monitors/{mon.id}", headers={"X-Aughor-Org": "d6mon_a"}).status_code == 204
    finally:
        delete_monitor(mon.id)
        registry.delete_connection(cid)


def test_monitor_list_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.monitors.store import delete_monitor

    cid = _mk_conn("d6mlist_a", "mlist-a-conn")
    mon = _mk_monitor(cid, "mlist-mon")
    try:
        seen_a = {m["id"] for m in client.get("/monitors", headers={"X-Aughor-Org": "d6mlist_a"}).json()}
        seen_b = {m["id"] for m in client.get("/monitors", headers={"X-Aughor-Org": "d6mlist_b"}).json()}
        assert mon.id in seen_a, "org sees its own monitor"
        assert mon.id not in seen_b, "org must NOT see another org's monitor"
    finally:
        delete_monitor(mon.id)
        registry.delete_connection(cid)


def test_alert_ack_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.monitors.store import delete_monitor, get_alert

    cid = _mk_conn("d6alert_a", "alert-a-conn")
    mon = _mk_monitor(cid, "alert-mon")
    alert = _mk_alert(cid, mon.id)
    try:
        # wrong org cannot acknowledge another org's alert
        assert client.post(f"/alerts/{alert.id}/acknowledge", headers={"X-Aughor-Org": "d6alert_b"}).status_code == 403
        assert not get_alert(alert.id).acknowledged, "the ack was blocked, not merely hidden"
        # owner can, and it sticks
        assert client.post(f"/alerts/{alert.id}/acknowledge", headers={"X-Aughor-Org": "d6alert_a"}).status_code == 200
        assert get_alert(alert.id).acknowledged
    finally:
        delete_monitor(mon.id)
        registry.delete_connection(cid)


def test_alert_feed_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.monitors.store import delete_monitor

    cid = _mk_conn("d6feed_a", "feed-a-conn")
    mon = _mk_monitor(cid, "feed-mon")
    alert = _mk_alert(cid, mon.id)
    try:
        seen_a = {a["id"] for a in client.get("/alerts", headers={"X-Aughor-Org": "d6feed_a"}).json()}
        seen_b = {a["id"] for a in client.get("/alerts", headers={"X-Aughor-Org": "d6feed_b"}).json()}
        assert alert.id in seen_a
        assert alert.id not in seen_b, "another org's alert must not leak into the feed"
    finally:
        delete_monitor(mon.id)
        registry.delete_connection(cid)


def test_create_monitor_on_foreign_connection_403(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry

    cid = _mk_conn("d6cm_a", "cm-a-conn")  # owned by org A
    try:
        # org B cannot attach a monitor to org A's connection
        r = client.post(
            "/monitors",
            json={"conn_id": cid, "name": "sneaky", "custom_sql": "SELECT 1"},
            headers={"X-Aughor-Org": "d6cm_b"},
        )
        assert r.status_code == 403
    finally:
        registry.delete_connection(cid)


# ── Brief subscriptions ───────────────────────────────────────────────────────────

def test_brief_by_id_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.briefs.store import delete_subscription

    cid = _mk_conn("d6brief_a", "brief-a-conn")
    sub = _mk_subscription(cid)
    try:
        assert client.delete(f"/briefs/subscriptions/{sub.id}", headers={"X-Aughor-Org": "d6brief_b"}).status_code == 403
        assert client.delete(f"/briefs/subscriptions/{sub.id}", headers={"X-Aughor-Org": "d6brief_a"}).status_code == 204
    finally:
        delete_subscription(sub.id)
        registry.delete_connection(cid)


def test_brief_list_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.briefs.store import delete_subscription

    cid = _mk_conn("d6blist_a", "blist-a-conn")
    sub = _mk_subscription(cid, "blist-sub")
    try:
        got_a = client.get("/briefs/subscriptions", headers={"X-Aughor-Org": "d6blist_a"}).json()["subscriptions"]
        got_b = client.get("/briefs/subscriptions", headers={"X-Aughor-Org": "d6blist_b"}).json()["subscriptions"]
        assert sub.id in {s["id"] for s in got_a}
        assert sub.id not in {s["id"] for s in got_b}
    finally:
        delete_subscription(sub.id)
        registry.delete_connection(cid)


# ── Saved queries ─────────────────────────────────────────────────────────────────

def test_saved_query_by_id_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.savedquery.store import create_saved_query, delete_saved_query

    cid = _mk_conn("d6sq_a", "sq-a-conn")
    q = create_saved_query(cid, "sq-a", "SELECT 1", {})
    try:
        assert client.get(f"/saved-queries/{q.id}", headers={"X-Aughor-Org": "d6sq_b"}).status_code == 403
        assert client.get(f"/saved-queries/{q.id}", headers={"X-Aughor-Org": "d6sq_a"}).status_code == 200
        assert client.delete(f"/saved-queries/{q.id}", headers={"X-Aughor-Org": "d6sq_b"}).status_code == 403
        # list is org-scoped too
        seen_b = {s["id"] for s in client.get("/saved-queries", headers={"X-Aughor-Org": "d6sq_b"}).json()}
        assert q.id not in seen_b
    finally:
        delete_saved_query(q.id)
        registry.delete_connection(cid)


# ── Canvases ──────────────────────────────────────────────────────────────────────

def test_canvas_list_is_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.canvas.store import create_canvas, delete_canvas
    from aughor.canvas.models import CanvasScope

    cid = _mk_conn("d6canv_a", "canv-a-conn")
    canvas = create_canvas(name="canv-a", scopes=[CanvasScope(connection_id=cid)])
    try:
        seen_a = {c["id"] for c in client.get("/canvases", headers={"X-Aughor-Org": "d6canv_a"}).json()}
        seen_b = {c["id"] for c in client.get("/canvases", headers={"X-Aughor-Org": "d6canv_b"}).json()}
        assert canvas.id in seen_a
        assert canvas.id not in seen_b, "another org's canvas must not appear in the list"
    finally:
        delete_canvas(canvas.id)
        registry.delete_connection(cid)


# ── Localhost mode: identity off → nothing is filtered or blocked ─────────────────

def test_localhost_mode_unchanged(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    from aughor.db import registry
    from aughor.monitors.store import delete_monitor
    from aughor.org.context import using_org

    with using_org("someorg"):
        cid = registry.add_connection("localhost-conn", "duckdb", "data/aughor.duckdb")
    mon = _mk_monitor(cid, "localhost-mon")
    try:
        # No header, a different org context — identity off means no scoping, no 403.
        assert client.get(f"/monitors/{mon.id}").status_code == 200
        seen = {m["id"] for m in client.get("/monitors").json()}
        assert mon.id in seen
    finally:
        delete_monitor(mon.id)
        registry.delete_connection(cid)


# ── Scheduler org re-bind ─────────────────────────────────────────────────────────

def test_scheduler_rebinds_connection_org(monkeypatch):
    """A background monitor tick carries no request context; trigger_now must bind the
    connection's org for the run so the emitted alert stamps the right tenant."""
    from aughor.db import registry
    from aughor.monitors.store import delete_monitor
    from aughor.org.context import current_org_id
    from aughor.monitors import scheduler
    import aughor.monitors.runner as runner_mod
    import aughor.db.connection as dbconn

    cid = _mk_conn("d6sched", "sched-conn")
    mon = _mk_monitor(cid, "sched-mon")
    captured: dict[str, str] = {}

    class _DummyDB:
        def close(self):
            pass

    def _fake_run(monitor, db, **kw):
        captured["org"] = current_org_id()
        return None

    monkeypatch.setattr(dbconn, "open_connection_for", lambda _cid: _DummyDB())
    monkeypatch.setattr(runner_mod, "run_monitor", _fake_run)
    try:
        # current org is 'default' here — the rebind must lift it to the connection's org
        scheduler.trigger_now(mon.id)
        assert captured.get("org") == "d6sched"
    finally:
        delete_monitor(mon.id)
        registry.delete_connection(cid)
