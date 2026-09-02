"""S1 — the embedded Qdrant backend: semantic search with no second process.

The receipt §3.6 asks for, as tests: with nothing pinned and no Postgres, the seam
opens qdrant-client's in-process local mode at AUGHOR_QDRANT_PATH and a write→read
roundtrip works — no server, no port, no env var beyond the suite's own isolation.

Real local mode on a temp path rather than fakes, for the same reason the pgvector
suite runs against a live server: similarity ordering and filter semantics are the
backend's behaviour, not mockable. Unlike that suite this one never skips — local
mode ships inside the pinned client package, which is the entire point of S1.
"""
from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")

from aughor.semantic import vector_store as V  # noqa: E402


@pytest.fixture()
def embedded(monkeypatch, tmp_path):
    """The unpinned-laptop shape: no server URL, no Postgres, a fresh index dir."""
    monkeypatch.delenv(V.QDRANT_URL_ENV, raising=False)
    monkeypatch.delenv("AUGHOR_DB_URL", raising=False)
    monkeypatch.setenv(V.QDRANT_PATH_ENV, str(tmp_path / "qdrant"))
    assert V.backend() == "qdrant" and V.available()
    return tmp_path / "qdrant"


def _vec(x: float) -> list[float]:
    v = [0.0] * V.VECTOR_DIM
    v[0] = x
    v[1] = (1 - x ** 2) ** 0.5      # unit-length so cosine scores are exact
    return v


def _seed():
    V.ensure_collection("t_embed")
    V.upsert("t_embed", [
        {"id": "a", "vector": _vec(1.0), "payload": {"name": "exact", "conn": "c1"}},
        {"id": "b", "vector": _vec(0.9), "payload": {"name": "near", "conn": "c1"}},
        {"id": "c", "vector": _vec(0.1), "payload": {"name": "far", "conn": "c2"}},
    ])


# ── selection ────────────────────────────────────────────────────────────────────

def test_unpinned_local_shape_runs_embedded_not_a_server(embedded):
    client = V._client()
    assert isinstance(client, V._Serialized), (
        "with no AUGHOR_QDRANT_URL the client must be the embedded singleton — a "
        "server client here means a fresh clone is back to needing docker compose")


def test_a_pinned_url_still_means_a_server(monkeypatch):
    from qdrant_client import QdrantClient
    monkeypatch.setenv(V.QDRANT_URL_ENV, "http://localhost:6333")
    client = V._client()
    assert isinstance(client, QdrantClient) and not isinstance(client, V._Serialized), (
        "an explicit AUGHOR_QDRANT_URL pins the server backend — deployments with "
        "an existing Qdrant (and their vectors) must keep exactly today's behaviour")


def test_the_embedded_client_is_one_per_path(embedded, monkeypatch, tmp_path):
    """Local mode holds an exclusive lock on its directory; a second client at the
    same path would be refused by qdrant itself. One cached client per path is what
    turns that lock from a crash into a property — and a DIFFERENT path must get a
    different index, or a test's temp dir would silently read the app's."""
    a, b = V._client(), V._client()
    assert a is b
    monkeypatch.setenv(V.QDRANT_PATH_ENV, str(tmp_path / "elsewhere"))
    assert V._client() is not a


def test_the_default_path_rides_the_state_dir(monkeypatch, tmp_path):
    """Unset, the index lives under state_dir() — so the suite's AUGHOR_STATE_DIR
    isolation and any whole-deployment data/ move carry it along."""
    monkeypatch.delenv(V.QDRANT_PATH_ENV, raising=False)
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    assert V._embedded_path() == str(tmp_path / "state" / "qdrant")


# ── the receipt: a real write→read roundtrip, no second process ──────────────────

def test_upsert_then_search_returns_ranked_hits(embedded):
    _seed()
    hits = V.search("t_embed", _vec(1.0), top_k=2)
    assert [h["payload"]["name"] for h in hits] == ["exact", "near"]
    assert hits[0]["score"] > hits[1]["score"]


def test_match_filter_scopes_the_search(embedded):
    _seed()
    hits = V.search("t_embed", _vec(1.0), top_k=5,
                    query_filter=V.match_filter("conn", "c2"))
    assert [h["payload"]["name"] for h in hits] == ["far"]


def test_counts_scroll_and_deletes_work_embedded(embedded):
    _seed()
    assert V.collection_count("t_embed") == 3
    assert V.collection_dim("t_embed") == V.VECTOR_DIM
    assert {p["name"] for p in V.scroll_payloads("t_embed")} == {"exact", "near", "far"}
    assert V.delete_by_filter("t_embed", V.match_filter("conn", "c1")) == 2
    assert V.collection_count("t_embed") == 1


def test_scroll_points_carries_the_id_delete_ids_uses_it(embedded):
    """The pair org intelligence needs: a listed row must be addressable, and the id
    that lists is the id that deletes."""
    _seed()
    points = V.scroll_points("t_embed")
    assert len(points) == 3 and all(p["id"] for p in points)
    far = next(p for p in points if p["payload"]["name"] == "far")
    assert V.delete_ids("t_embed", [far["id"]]) is True
    assert {p["payload"]["name"] for p in V.scroll_points("t_embed")} == {"exact", "near"}


def test_the_index_persists_across_clients_on_one_path(embedded, monkeypatch, tmp_path):
    """On-disk, not in-memory: a second client on the same directory sees the data.
    Simulated by evicting the cache rather than a second process — the lock forbids
    two live clients, which is exactly why the cache exists."""
    _seed()
    with V._embedded_guard:
        V._embedded.clear()
    assert V.collection_count("t_embed") == 3


def test_org_intelligence_list_and_delete_ride_the_seam(embedded, monkeypatch):
    """The end-to-end that was impossible before: promote → list (with id) → delete
    by that id, all against the embedded index. The old bespoke clients talked to
    localhost:6333 regardless of where the real index lived."""
    from aughor.knowledge import org_intelligence as OI
    monkeypatch.setattr("aughor.semantic.embedder.embed_one", lambda text: _vec(1.0))

    OI.promote_to_org("i1", "revenue dips on Sundays", "retail", 4, "cv1",
                      connection_id="c1")
    rows = OI.list_org_intelligence()
    assert [r["insight_id"] for r in rows] == ["i1"]
    assert OI.delete_org_insight(rows[0]["id"]) is True
    assert OI.list_org_intelligence() == []
