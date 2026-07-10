"""Org-intelligence scoping — the Hub is a scoped surface and must not blend
every connection's (or schema's) promoted insights together; the unscoped
org-wide view is the Org layer's job. Hermetic: Qdrant is faked."""
from __future__ import annotations


class _FakePoint:
    def __init__(self, pid: int, payload: dict):
        self.id = pid
        self.payload = payload


class _FakeQdrant:
    _POINTS = [
        _FakePoint(1, {"insight_id": "a", "text": "t1", "connection_id": "conn1",
                       "schema": "sales", "promoted_at": "2026-07-02"}),
        _FakePoint(2, {"insight_id": "b", "text": "t2", "connection_id": "conn1",
                       "schema": "ops", "promoted_at": "2026-07-03"}),
        _FakePoint(3, {"insight_id": "c", "text": "t3", "connection_id": "conn2",
                       "schema": "sales", "promoted_at": "2026-07-04"}),
        # promoted before scoping existed — no connection_id/schema recorded
        _FakePoint(4, {"insight_id": "legacy", "text": "t4", "promoted_at": "2026-07-01"}),
    ]

    def __init__(self, url: str):
        pass

    def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        return list(self._POINTS), None


def _patched(monkeypatch):
    import qdrant_client
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrant)


def test_unscoped_returns_everything_newest_first(monkeypatch):
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    out = list_org_intelligence()
    assert [r["insight_id"] for r in out] == ["c", "b", "a", "legacy"]


def test_connection_scope_filters(monkeypatch):
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    out = list_org_intelligence(connection_id="conn1")
    assert {r["insight_id"] for r in out} == {"a", "b"}


def test_connection_and_schema_scope_filters(monkeypatch):
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    out = list_org_intelligence(connection_id="conn1", schema="sales")
    assert [r["insight_id"] for r in out] == ["a"]


def test_legacy_unattributed_rows_stay_out_of_scoped_views(monkeypatch):
    """Insights promoted before scoping carry no connection_id; they appear only
    in the unscoped org-wide view, never inside another connection's Hub."""
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    for conn in ("conn1", "conn2", "conn3"):
        assert all(r["insight_id"] != "legacy" for r in list_org_intelligence(connection_id=conn))
    assert any(r["insight_id"] == "legacy" for r in list_org_intelligence())
