"""Restoring schema documentation from its persisted artifact.

`/documents/reindex` re-embeds what the store holds. That is everything an upload has —
`index_file` unlinks the file — and it is NOT everything a schema doc has: the ontology
compiles those to a doc tree on disk first, so the artifact outlives the collection. The
store here held 5 chunks for a document whose artifact held 59, and nothing could put them
back short of re-running intelligence over the connection.

Hermetic in the same way as `test_doctree_knowledge.py`: embedder and vector store are
monkeypatched at their module seams, the registry rides a temp override, and the doc-tree
root is re-pointed per test (`_root()` reads its env var at call time, so this is real
isolation and not a silent no-op).
"""
from __future__ import annotations

import pytest

import aughor.knowledge.indexer as idx
import aughor.knowledge.reindex as rx


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """A doc-tree root, an isolated registry, a fake store, and one live connection."""
    state = {"upserts": [], "deleted": [], "payloads": [], "owned": set()}
    monkeypatch.setenv("AUGHOR_ONTOLOGY_DOCS_DIR", str(tmp_path / "ontology_docs"))
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(tmp_path / "documents.json"))
    monkeypatch.setattr("aughor.semantic.embedder.embed",
                        lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection",
                        lambda coll, dim=None: None)
    monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda coll: 8)
    # The ACTIVE width, stubbed rather than probed. `embedding_dim()` memoizes into a
    # module-level `_DIM_CACHE` keyed by (backend, model), and that cache outlives
    # monkeypatch: run alone this fixture's fake embedder probes 8, but in a full suite an
    # earlier test has already cached 768 for the same key, so `_ensure_collection` compares
    # 768 against the 8 above and refuses every write. The sibling fixture in
    # test_reindex_path.py stubs it for the same reason.
    monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: 8)
    # Capture only the documents this test persisted. Something in the wider suite
    # re-indexes a doc tree from a thread that outlives the request that started it, into
    # THIS collection — observed as `doc::doctree::fixture::default::0` landing in the
    # middle of an unrelated test. Filtering by collection alone is not enough, because
    # the stranger writes to the same collection; ownership is the property that holds.
    def _upsert(coll, points):
        if coll != idx.DOCS_COLLECTION:
            return
        state["upserts"].extend(
            p for p in points
            if str((p.get("payload") or {}).get("doc_id") or "") in state["owned"])
    monkeypatch.setattr("aughor.semantic.vector_store.upsert", _upsert)
    monkeypatch.setattr("aughor.semantic.vector_store.scroll_payloads",
                        lambda coll, limit=0: list(state["payloads"]))
    monkeypatch.setattr(idx, "_delete_doc_chunks",
                        lambda doc_id: state["deleted"].append(doc_id))
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "connZ"}])
    return state


def _persist(env=None, conn: str = "connZ", schema: str = "s", *, tables: int = 2):
    """Build a doc tree with `tables` table nodes and leave it on disk, as a build would.

    Records the doc_id it created in `env["owned"]` so the upsert capture can tell this
    test's writes from a stranger's.
    """
    from aughor.ontology.doctree import build_doc_tree, save_doc_tree
    from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph

    entities = {}
    for i in range(tables):
        entities[f"sales{i}"] = OntologyEntity(
            id=f"sales{i}", display_name=f"Sales {i}", source_tables=[f"sales{i}"],
            identity_key="id", grain_verified=True,
            properties={
                "brand": EntityProperty(name="brand", data_type="VARCHAR",
                                        semantic_type="dimension"),
                "amount": EntityProperty(name="amount", data_type="DOUBLE",
                                         semantic_type="measure"),
            },
        )
    graph = OntologyGraph(connection_id=conn, schema_name=schema,
                          schema_fingerprint="f", entities=entities)
    tree = build_doc_tree(graph, table_stats={f"sales{i}": {"row_count": 42}
                                              for i in range(tables)})
    save_doc_tree(tree)
    if env is not None:
        env["owned"].add(f"doctree::{conn}::{schema or 'default'}")
    return tree


# ── the artifact is discoverable by what it SAYS it is ────────────────────────────────

def test_persisted_trees_are_read_from_the_manifest_not_the_directory_name(env):
    """`_safe` mangles an id into a directory name; un-mangling it would guess wrong."""
    from aughor.ontology.doctree import list_persisted_trees

    _persist(env, conn="conn/Z:odd", schema="s")
    # The directory is mangled, so a reader that trusted it would report the wrong id.
    assert list_persisted_trees() == [("conn/Z:odd", "s")]


def test_an_unreadable_manifest_is_skipped_not_fatal(env, tmp_path):
    from aughor.ontology.doctree import list_persisted_trees

    _persist(env)
    broken = tmp_path / "ontology_docs" / "broken" / "main"
    broken.mkdir(parents=True)
    (broken / "tree.yaml").write_text("{ this is not: valid: yaml ]")
    assert list_persisted_trees() == [("connZ", "s")]


# ── the chunk rule has exactly one copy ───────────────────────────────────────────────

def test_planned_chunks_are_the_chunks_that_get_written(env):
    """The count a person decides a restore on must be the count the write produces."""
    tree = _persist(env, tables=3)
    planned = idx.doctree_chunks(tree, connection_id="connZ", schema="s")
    written = idx.index_doc_tree(tree, connection_id="connZ", schema="s")

    assert len(planned) == written["chunk_count"] == 3
    assert [c.fqn for c in planned] == [p["payload"]["fqn"] for p in env["upserts"]]


# ── the plan ──────────────────────────────────────────────────────────────────────────

def test_plan_reports_what_each_document_would_gain(env):
    _persist(env, tables=3)
    env["payloads"] = [{"doc_id": "doctree::connZ::s"}]  # the store kept one of three

    plan = rx.doctree_plan()
    assert plan["documents"] == [
        {"doc_id": "doctree::connZ::s", "in_store": 1, "in_artifact": 3, "adds": 2}]
    assert plan["restorable_chunks"] == 2
    assert plan["skipped"] == []


def test_an_artifact_outliving_its_connection_is_skipped_with_the_reason(env, monkeypatch):
    """A restore that ignored the registry would put back what a purge just removed."""
    _persist(env, conn="deleted_conn", schema="s")
    _persist(env, conn="connZ", schema="s")

    plan = rx.doctree_plan()
    assert [d["doc_id"] for d in plan["documents"]] == ["doctree::connZ::s"]
    assert [s["doc_id"] for s in plan["skipped"]] == ["doctree::deleted_conn::s"]
    assert "no such connection" in plan["skipped"][0]["reason"]

    # Prove the guard is what excludes it: make the connection live and it comes back.
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "connZ"}, {"id": "deleted_conn"}])
    assert len(rx.doctree_plan()["documents"]) == 2


def test_plan_can_be_scoped_to_one_connection(env, monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "connZ"}, {"id": "other"}])
    _persist(env, conn="connZ", schema="s")
    _persist(env, conn="other", schema="s")

    plan = rx.doctree_plan(connection_id="other")
    assert [d["doc_id"] for d in plan["documents"]] == ["doctree::other::s"]


# ── the restore ───────────────────────────────────────────────────────────────────────

def test_restore_writes_the_artifact_back(env):
    _persist(env, tables=3)
    env["payloads"] = [{"doc_id": "doctree::connZ::s"}]

    out = rx.doctree_restore()
    assert out["ok"] is True
    assert out["chunks_written"] == 3
    assert out["failed"] == []
    assert len(env["upserts"]) == 3
    # Replaced, not accumulated.
    assert env["deleted"] == ["doctree::connZ::s"]


def test_a_failing_document_is_named_and_does_not_stop_the_others(env, monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda org_id=None: [{"id": "connZ"}, {"id": "other"}])
    _persist(env, conn="connZ", schema="s")
    _persist(env, conn="other", schema="s")

    real = idx.index_doc_tree

    def flaky(tree, *, connection_id, schema=""):
        if connection_id == "connZ":
            raise RuntimeError("embedder is down")
        return real(tree, connection_id=connection_id, schema=schema)

    monkeypatch.setattr(idx, "index_doc_tree", flaky)
    out = rx.doctree_restore()

    assert out["ok"] is False
    assert [f["doc_id"] for f in out["failed"]] == ["doctree::connZ::s"]
    assert "embedder is down" in out["failed"][0]["error"]
    assert [r["doc_id"] for r in out["restored"]] == ["doctree::other::s"]


# ── the number that was wrong ─────────────────────────────────────────────────────────

def test_unrecoverable_excludes_what_an_artifact_can_supply(env, monkeypatch):
    """The claim was true for uploads and false for schema docs; both now report right."""
    _persist(env, tables=3)
    env["payloads"] = [{"doc_id": "doctree::connZ::s"}, {"doc_id": "upload::a"}]
    monkeypatch.setattr("aughor.knowledge.indexer.list_documents", lambda: [
        {"doc_id": "doctree::connZ::s", "chunk_count": 3},   # 2 missing, artifact has them
        {"doc_id": "upload::a", "chunk_count": 5},           # 4 missing, gone for good
    ])

    plan = rx.plan()
    assert plan["restorable_from_doctrees"] == 2
    assert plan["unrecoverable_chunks"] == 4


def test_without_an_artifact_the_old_pessimistic_number_stands(env, monkeypatch):
    """Proves the correction is the artifact and not a change of arithmetic."""
    env["payloads"] = [{"doc_id": "doctree::connZ::s"}]
    monkeypatch.setattr("aughor.knowledge.indexer.list_documents", lambda: [
        {"doc_id": "doctree::connZ::s", "chunk_count": 3},
    ])

    plan = rx.plan()  # no tree persisted
    assert plan["restorable_from_doctrees"] == 0
    assert plan["unrecoverable_chunks"] == 2


# ── through the route, not just the function ──────────────────────────────────────────

def test_the_route_plans_by_default_and_restores_when_asked(env):
    """`dry_run` defaults TRUE on the destructive sibling; a caller that forgets it here
    must get a plan, not a rebuild."""
    from fastapi.testclient import TestClient

    from aughor.api import app
    client = TestClient(app)

    _persist(env, tables=3)
    env["payloads"] = [{"doc_id": "doctree::connZ::s"}]

    planned = client.post("/documents/restore-doctrees", json={})
    assert planned.status_code == 200
    assert planned.json()["dry_run"] is True
    assert planned.json()["restorable_chunks"] == 2
    assert env["upserts"] == []  # a plan writes nothing

    done = client.post("/documents/restore-doctrees", json={"dry_run": False})
    assert done.status_code == 200
    assert done.json()["dry_run"] is False
    assert done.json()["chunks_written"] == 3
    assert len(env["upserts"]) == 3
