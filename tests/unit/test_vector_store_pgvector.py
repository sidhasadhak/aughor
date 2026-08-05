"""The pgvector backend of the semantic-index seam, proven on a live server.

Runs against a pgvector-enabled Postgres (AUGHOR_PGVECTOR_TEST_URL, defaulting to
the local pgvector/pgvector:pg16 container) and SKIPS when none is reachable —
similarity ordering and filter semantics are server behaviour, not mockable.
"""
from __future__ import annotations

import os

import pytest

from aughor.semantic import vector_store as V

PG_URL = os.environ.get("AUGHOR_PGVECTOR_TEST_URL",
                        "postgres://postgres:aughor@localhost:5545/aughor")


def _pgvector_available() -> bool:
    try:
        import psycopg2
        conn = psycopg2.connect(PG_URL, connect_timeout=2)
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pgvector_available(),
                                reason="needs a live Postgres with pgvector")


@pytest.fixture(autouse=True)
def pg_backend(monkeypatch):
    """Select the pgvector backend the way a deployment does: AUGHOR_DB_URL set,
    no explicit Qdrant URL. Each test gets a clean collection namespace."""
    monkeypatch.delenv(V.QDRANT_URL_ENV, raising=False)
    monkeypatch.setenv("AUGHOR_DB_URL", PG_URL)
    assert V.backend() == "pgvector" and V.available()
    yield
    V.delete_by_filter("t_probe", V.match_filter("suite", "pgvector"))


def _vec(x: float) -> list[float]:
    v = [0.0] * V.VECTOR_DIM
    v[0] = x
    v[1] = (1 - x ** 2) ** 0.5      # unit-length so cosine scores are exact
    return v


def _seed():
    V.ensure_collection("t_probe")
    V.upsert("t_probe", [
        {"id": "a", "vector": _vec(1.0),
         "payload": {"suite": "pgvector", "connection_id": "c1", "name": "exact"}},
        {"id": "b", "vector": _vec(0.9),
         "payload": {"suite": "pgvector", "connection_id": "c1", "name": "near"}},
        {"id": "c", "vector": _vec(0.0),
         "payload": {"suite": "pgvector", "connection_id": "c2", "name": "far"}},
    ])


def test_backend_selection_rules(monkeypatch):
    monkeypatch.setenv(V.QDRANT_URL_ENV, "http://somewhere:6333")
    assert V.backend() == "qdrant"          # explicit Qdrant URL pins Qdrant
    monkeypatch.delenv(V.QDRANT_URL_ENV, raising=False)
    assert V.backend() == "pgvector"        # AUGHOR_DB_URL alone → pgvector


def test_upsert_search_orders_by_similarity_and_scores_cosine():
    _seed()
    hits = V.search("t_probe", _vec(1.0), top_k=3,
                    query_filter=V.match_filter("suite", "pgvector"))
    names = [h["payload"]["name"] for h in hits]
    assert names == ["exact", "near", "far"]
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)
    assert hits[0]["score"] > hits[1]["score"] > hits[2]["score"]


def test_match_filter_narrows_and_upsert_replaces():
    _seed()
    hits = V.search("t_probe", _vec(1.0), top_k=10,
                    query_filter=V.match_filter("connection_id", "c2"))
    assert [h["payload"]["name"] for h in hits] == ["far"]
    # same id upserts in place — no duplicate rows
    V.upsert("t_probe", [{"id": "a", "vector": _vec(1.0),
                          "payload": {"suite": "pgvector", "connection_id": "c1",
                                      "name": "exact-v2"}}])
    hits = V.search("t_probe", _vec(1.0), top_k=1,
                    query_filter=V.match_filter("connection_id", "c1"))
    assert hits[0]["payload"]["name"] == "exact-v2"


def test_count_scroll_and_filtered_delete():
    _seed()
    assert V.collection_count("t_probe") >= 3
    payloads = V.scroll_payloads("t_probe")
    assert {"exact", "near", "far"} <= {p.get("name") for p in payloads}
    # the purge-hook path: delete one connection's vectors, the other survives
    n = V.delete_by_filter("t_probe", V.match_filter("connection_id", "c1"))
    assert n == 2
    remaining = V.scroll_payloads("t_probe")
    assert {p.get("name") for p in remaining if p.get("suite") == "pgvector"} == {"far"}
