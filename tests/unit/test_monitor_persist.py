"""Monitor store round-trip — post-schema fields (reanchor_window) survive save/reload
via the `extra` JSON blob. Regression: reanchor_window was dropped on persist, so a
re-anchoring monitor reloaded as reanchor_window=False and never re-anchored at run time.
"""
import importlib

import aughor.monitors.store as store
from aughor.monitors.models import Monitor


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "monitors.db")
    store._init_schema()


def test_reanchor_window_persists(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    m = Monitor(conn_id="c1", name="m", custom_sql="SELECT 1", reanchor_window=True)
    store.upsert_monitor(m)
    reloaded = store.get_monitor(m.id)
    assert reloaded is not None
    assert reloaded.reanchor_window is True


def test_reanchor_window_defaults_false(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    m = Monitor(conn_id="c1", name="m", custom_sql="SELECT 1")
    store.upsert_monitor(m)
    assert store.get_monitor(m.id).reanchor_window is False


def test_update_preserves_reanchor_window(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    m = Monitor(conn_id="c1", name="m", custom_sql="SELECT 1", reanchor_window=True)
    store.upsert_monitor(m)
    # update an unrelated field; reanchor_window must survive the upsert
    store.upsert_monitor(store.get_monitor(m.id).model_copy(update={"name": "renamed"}))
    reloaded = store.get_monitor(m.id)
    assert reloaded.name == "renamed" and reloaded.reanchor_window is True
