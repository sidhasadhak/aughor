"""Workspace tenancy gate on the monitors + alerts list endpoints.

Regression guard for a data-path leak: an empty or foreign workspace must not
surface another connection's monitors or alerts. The leak was reachable via
MonitorsPanel, which fired ``GET /monitors`` and ``GET /alerts`` with no
connection selected (``connId`` undefined) → the endpoints listed *every*
workspace's rows. Fixed by threading ``workspace_id`` through and applying the
fail-closed ``workspace_connection_ids`` gate (None=unscoped, set=scoped,
empty-set=unknown workspace surfaces nothing).
"""
import aughor.monitors.store as mstore
import aughor.workspace.store as wstore
from aughor.monitors.models import Monitor, MonitorAlert
from aughor.routers.monitors import get_all_alerts, list_monitors_route


def _seed(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(mstore, "_DB_PATH", tmp_path / "monitors.db")
    mstore._init_schema()
    monkeypatch.setattr(wstore, "_DB_PATH", tmp_path / "workspaces.db")
    # The data-path gate now resolves through the metastore — keep it hermetic too.
    import aughor.metastore.store as cat_store
    monkeypatch.setattr(cat_store, "_DB_PATH", tmp_path / "metastore.db")

    mstore.upsert_monitor(Monitor(conn_id="c1", name="m1", custom_sql="SELECT 1"))
    mstore.upsert_monitor(Monitor(conn_id="c2", name="m2", custom_sql="SELECT 1"))
    mstore.append_alert(MonitorAlert(monitor_id="a1", conn_id="c1", triggered_at="2026-01-01T00:00:00Z"))
    mstore.append_alert(MonitorAlert(monitor_id="a2", conn_id="c2", triggered_at="2026-01-01T00:00:00Z"))
    # A workspace that contains only c1 — c2 is "another workspace's" connection.
    return wstore.create_workspace(name="only-c1", connection_ids=["c1"]).id


def test_monitors_scoped_to_workspace(tmp_path, monkeypatch):
    ws_id = _seed(tmp_path, monkeypatch)
    assert {m["conn_id"] for m in list_monitors_route(workspace_id=ws_id)} == {"c1"}


def test_monitors_unknown_workspace_is_fail_closed(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert list_monitors_route(workspace_id="does-not-exist") == []


def test_monitors_unscoped_returns_all(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert {m["conn_id"] for m in list_monitors_route(workspace_id=None)} == {"c1", "c2"}


def test_alerts_scoped_to_workspace(tmp_path, monkeypatch):
    ws_id = _seed(tmp_path, monkeypatch)
    assert {a["conn_id"] for a in get_all_alerts(workspace_id=ws_id)} == {"c1"}


def test_alerts_unknown_workspace_is_fail_closed(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert get_all_alerts(workspace_id="does-not-exist") == []


def test_alerts_unscoped_returns_all(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert {a["conn_id"] for a in get_all_alerts(workspace_id=None)} == {"c1", "c2"}
