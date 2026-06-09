"""Temporal Tier 3 — incremental re-exploration watermark. See aughor/explorer/watermark.py."""
import aughor.explorer.watermark as wm


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(wm, "_PATH", tmp_path / "wm.json")


def test_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert wm.get_watermark("c1", "orders") is None
    wm.set_watermark("c1", "orders", "2026-05-17")
    assert wm.get_watermark("c1", "orders") == "2026-05-17"
    # scoped per (connection, table)
    assert wm.get_watermark("c1", "other") is None
    assert wm.get_watermark("c2", "orders") is None


def test_set_ignores_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    wm.set_watermark("c1", "orders", None)
    wm.set_watermark("c1", "orders", "")
    assert wm.get_watermark("c1", "orders") is None


def test_clear(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    wm.set_watermark("c1", "orders", "2026-01-01")
    wm.set_watermark("c1", "items", "2026-02-01")
    wm.clear_watermark("c1", "orders")
    assert wm.get_watermark("c1", "orders") is None
    assert wm.get_watermark("c1", "items") == "2026-02-01"
    wm.clear_watermark("c1")  # whole connection
    assert wm.get_watermark("c1", "items") is None


def test_delta_clause():
    assert wm.delta_clause("order_ts", "2026-05-17") == "order_ts > '2026-05-17'"
    assert wm.delta_clause("order_ts", None) == ""       # no watermark → full scan
    assert wm.delta_clause("", "2026-05-17") == ""        # no timestamp col → full scan
    # quote-injection defanged
    assert "''" not in wm.delta_clause("ts", "2026'; DROP")
