"""Documents pinned to a canvas — the workspace half of "usable anywhere".

Agents could already bind documents and chat could already retrieve them. A canvas —
the thing a person actually works inside — had no document wiring at all: grep
`aughor/canvas/` for `doc_id` before this and there were zero hits. Its documents were
reachable only if a global similarity search happened to rank them, which is not what
attaching a document to a workspace means.

The two scopes are deliberately different shapes, and these tests pin that difference
because it is the kind of thing a later refactor would "tidy" into one:

  * An AGENT's documents RESTRICT — an agent with none sees none, fail-closed,
    because its context is what its creator gave it.
  * A CANVAS's documents PIN — binding one adds it to what is in reach without
    removing the rest of the corpus, because a canvas is a place, not a fence.

Pinning is bounded rather than wholesale: pinned documents are searched against the
same question and only their relevant passages are placed first. A 200-chunk report
pinned to a workspace must not flood every prompt.
"""
from __future__ import annotations

import pytest

from aughor.canvas.models import CanvasScope
from aughor.canvas.store import create_canvas, get_canvas, update_canvas


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch):
    """Index without reaching a live embedder.

    These tests upload, and uploading embeds. A developer machine usually has a local
    embedder answering, and CI has none — so this file passed here and failed on the
    first machine without one, with a 500 and `Connection refused`. That is the
    "run the suite without what only your machine has" trap in its purest form: the
    thing under test never needed a real embedder, the test just silently used one.

    768 is the width the rest of the suite caches. `embedding_dim()` memoizes into a
    module-level cache that outlives monkeypatch, so a narrower fake would be compared
    against an earlier test's 768 and every write refused.
    """
    monkeypatch.setattr("aughor.semantic.embedder.embed",
                        lambda texts: [[0.0] * 768 for _ in texts])
    monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: 768)


@pytest.fixture
def canvas():
    return create_canvas(name="Q3 review",
                         scopes=[CanvasScope(connection_id="c1", tables=[])])


# ── The binding persists ──────────────────────────────────────────────────────

def test_a_canvas_starts_with_no_documents(canvas):
    """Empty is exactly today's behaviour — this feature is inert until used."""
    assert canvas.doc_ids == []
    assert get_canvas(canvas.id).doc_ids == []


def test_documents_bind_and_survive_a_reload(canvas):
    update_canvas(canvas.id, doc_ids=["doc-a", "doc-b"])
    assert get_canvas(canvas.id).doc_ids == ["doc-a", "doc-b"]


def test_none_leaves_the_binding_alone_but_empty_unbinds(canvas):
    """A single field has to express both, or unbinding is impossible."""
    update_canvas(canvas.id, doc_ids=["doc-a"])

    update_canvas(canvas.id, name="Renamed")               # doc_ids omitted
    assert get_canvas(canvas.id).doc_ids == ["doc-a"], "a rename dropped the binding"

    update_canvas(canvas.id, doc_ids=[])                   # explicit clear
    assert get_canvas(canvas.id).doc_ids == []


def test_a_canvas_can_be_created_with_documents():
    cv = create_canvas(name="With docs",
                       scopes=[CanvasScope(connection_id="c1")],
                       doc_ids=["doc-a"])
    assert get_canvas(cv.id).doc_ids == ["doc-a"]


def test_the_column_is_added_to_a_store_that_predates_it(tmp_path, monkeypatch):
    """An existing canvases.db has no `doc_ids_json`. The additive probe must bring
    it up to date rather than erroring, and canvases already in it must still load."""
    import sqlite3

    db = tmp_path / "old_canvases.db"
    old = sqlite3.connect(db)
    old.execute("""CREATE TABLE canvases (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
        scopes_json TEXT NOT NULL DEFAULT '[]', is_legacy INTEGER DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    old.execute("INSERT INTO canvases VALUES ('old1','Legacy','', '[]', 0, 'now', 'now')")
    old.commit()
    old.close()

    monkeypatch.setenv("AUGHOR_CANVAS_DB", str(db))
    import importlib

    from aughor.canvas import store as canvas_store
    importlib.reload(canvas_store)
    try:
        existing = canvas_store.get_canvas("old1")
        assert existing is not None, "a canvas from before the column failed to load"
        assert existing.doc_ids == []
        canvas_store.update_canvas("old1", doc_ids=["doc-a"])
        assert canvas_store.get_canvas("old1").doc_ids == ["doc-a"]
    finally:
        # A reloaded module leaves TWO live copies — put the original back, or every
        # later test in this process talks to the tmp_path DB.
        monkeypatch.undo()
        importlib.reload(canvas_store)


# ── The routes ────────────────────────────────────────────────────────────────

#: Long enough to clear `min_chars` (50). A shorter document is refused outright —
#: see `test_a_document_too_short_to_index_is_refused_not_silently_accepted`.
POLICY = (b"# Refund policy\n\nCustomers may return any item within 30 days of "
          b"delivery for a full refund, provided the packaging is intact.\n")


def _make_document(client, name: str = "policy.md") -> str:
    r = client.post("/documents/upload",
                    files={"file": (name, POLICY, "text/markdown")})
    assert r.status_code == 201, r.text
    return r.json()["doc_id"]


def test_binding_through_the_api_lists_the_document_back(client, canvas):
    doc_id = _make_document(client)

    r = client.put(f"/canvases/{canvas.id}", json={"doc_ids": [doc_id]})
    assert r.status_code == 200, r.text
    assert r.json()["doc_ids"] == [doc_id]

    listed = client.get(f"/canvases/{canvas.id}/documents").json()["documents"]
    assert len(listed) == 1
    assert listed[0]["doc_id"] == doc_id
    assert listed[0]["missing"] is False
    assert listed[0]["title"], "the row should carry the registry's metadata"


def test_binding_a_document_that_does_not_exist_is_refused(client, canvas):
    """A pin to a mistyped id fails SILENTLY at retrieval — it matches nothing and
    raises nowhere. Write time is the only moment the mistake is attributable."""
    r = client.put(f"/canvases/{canvas.id}", json={"doc_ids": ["not-a-real-doc"]})
    assert r.status_code == 422
    assert "not-a-real-doc" in r.json()["detail"]
    assert get_canvas(canvas.id).doc_ids == [], "a refused write must change nothing"


def test_a_deleted_document_is_reported_missing_rather_than_dropped(client, canvas):
    """A pin that silently vanishes is how a workspace loses context unnoticed."""
    doc_id = _make_document(client)
    client.put(f"/canvases/{canvas.id}", json={"doc_ids": [doc_id]})
    client.delete(f"/documents/{doc_id}")

    listed = client.get(f"/canvases/{canvas.id}/documents").json()["documents"]
    assert len(listed) == 1
    assert listed[0]["missing"] is True


def test_binding_the_same_document_twice_is_not_an_error(client, canvas):
    doc_id = _make_document(client)
    r = client.put(f"/canvases/{canvas.id}", json={"doc_ids": [doc_id, doc_id]})
    assert r.status_code == 200
    assert r.json()["doc_ids"] == [doc_id]


def test_documents_of_an_unknown_canvas_is_a_404(client):
    assert client.get("/canvases/nope/documents").status_code == 404


# ── The retrieval seam ────────────────────────────────────────────────────────

def test_a_canvas_with_no_documents_changes_nothing(monkeypatch, canvas):
    """The seam is inert on the default path — the property that makes it safe to
    add to an answer pipeline everyone already depends on."""
    from aughor.knowledge import indexer

    monkeypatch.setattr(indexer, "search_documents",
                        lambda q, top_k=4: [{"doc_id": "g1", "chunk_index": 0,
                                             "text": "global", "title": "Global",
                                             "filename": "g.md", "score": 0.9}])
    with_canvas = indexer.build_external_context_section("q", canvas_id=canvas.id)
    without = indexer.build_external_context_section("q")
    assert with_canvas == without
    assert "WORKSPACE DOCUMENTS" not in with_canvas


def test_pinned_documents_are_placed_first_and_labelled(monkeypatch, canvas):
    from aughor.knowledge import indexer

    update_canvas(canvas.id, doc_ids=["pinned1"])
    hits = [
        {"doc_id": "g1", "chunk_index": 0, "text": "global text", "title": "Global",
         "filename": "g.md", "score": 0.9},
        {"doc_id": "pinned1", "chunk_index": 0, "text": "pinned text",
         "title": "Pinned", "filename": "p.md", "score": 0.4},
    ]
    monkeypatch.setattr(indexer, "search_documents", lambda q, top_k=4: hits)

    section = indexer.build_external_context_section("q", canvas_id=canvas.id)

    assert "WORKSPACE DOCUMENTS" in section
    assert section.index("pinned text") < section.index("global text"), \
        "the pinned document must lead — that is what pinning means"


def test_a_pinned_document_is_not_repeated_in_the_general_block(monkeypatch, canvas):
    """It ranks in both searches; printing it twice wastes the context it was pinned
    to occupy."""
    from aughor.knowledge import indexer

    update_canvas(canvas.id, doc_ids=["pinned1"])
    hits = [{"doc_id": "pinned1", "chunk_index": 0, "text": "the only text",
             "title": "Pinned", "filename": "p.md", "score": 0.9}]
    monkeypatch.setattr(indexer, "search_documents", lambda q, top_k=4: hits)

    section = indexer.build_external_context_section("q", canvas_id=canvas.id)
    assert section.count("the only text") == 1


def test_an_agent_still_fences_what_a_canvas_pins(monkeypatch, canvas):
    """A canvas must not widen an agent past what it was given — that is the
    direction that turns a restriction into a suggestion."""
    from aughor.knowledge import indexer

    update_canvas(canvas.id, doc_ids=["pinned1"])
    monkeypatch.setattr(indexer, "search_documents",
                        lambda q, top_k=4: [{"doc_id": "pinned1", "chunk_index": 0,
                                             "text": "pinned text", "title": "Pinned",
                                             "filename": "p.md", "score": 0.9}])
    # An agent bound to a DIFFERENT document than the canvas pins.
    monkeypatch.setattr("aughor.custom_agents.context.agent_doc_ids",
                        lambda: {"agent-doc"})

    section = indexer.build_external_context_section("q", canvas_id=canvas.id)
    assert "pinned text" not in section, "the canvas widened the agent's fence"


def test_an_unreadable_canvas_degrades_instead_of_raising(monkeypatch):
    """Losing a pinned document costs context; raising would cost the reply."""
    from aughor.knowledge import indexer

    def boom(_):
        raise RuntimeError("canvas store is down")

    monkeypatch.setattr("aughor.canvas.store.get_canvas", boom)
    assert indexer.canvas_doc_ids("any-id") == []


def test_no_canvas_means_no_pins():
    from aughor.knowledge.indexer import canvas_doc_ids

    assert canvas_doc_ids(None) == []
    assert canvas_doc_ids("") == []
    assert canvas_doc_ids("does-not-exist") == []
