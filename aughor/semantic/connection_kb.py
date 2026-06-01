"""Per-connection knowledge store.

Lets users author business definitions, metric explanations, synonym maps,
and join notes that are specific to their database — and retrieves only the
relevant ones per question (unlike static prompt rules that dump everything).

Storage:  data/knowledge_{conn_id}.json
Vectors:  Qdrant collection  aughor_connection_kb  (filtered by connection_id)

Entry shape:
{
  "id":           "mrr_definition",
  "title":        "Monthly Recurring Revenue (MRR)",
  "kind":         "metric" | "synonym" | "rule" | "join" | "note",
  "body":         "MRR = SUM of active subscription amounts billed monthly.",
  "tags":         ["mrr", "revenue", "subscription"],
  "connection_id": "conn_abc123"
}
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Literal

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_COLLECTION = "aughor_connection_kb"
_MIN_SCORE   = 0.55   # lower than general KB — these are domain-specific so cast wider
_TOP_K       = 4

KnowledgeKind = Literal["metric", "synonym", "rule", "join", "note"]


# ── Data class ────────────────────────────────────────────────────────────────

class KnowledgeEntry:
    def __init__(
        self,
        id: str,
        title: str,
        body: str,
        kind: KnowledgeKind = "note",
        tags: list[str] | None = None,
        connection_id: str = "",
    ) -> None:
        self.id            = id
        self.title         = title
        self.body          = body
        self.kind          = kind
        self.tags          = tags or []
        self.connection_id = connection_id

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "title":         self.title,
            "body":          self.body,
            "kind":          self.kind,
            "tags":          self.tags,
            "connection_id": self.connection_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeEntry":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            title=d.get("title", ""),
            body=d.get("body", ""),
            kind=d.get("kind", "note"),
            tags=d.get("tags", []),
            connection_id=d.get("connection_id", ""),
        )

    def _stable_id(self) -> str:
        key = f"{self.connection_id}:{self.id}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def render(self) -> str:
        kind_label = {
            "metric":  "METRIC DEFINITION",
            "synonym": "SYNONYM",
            "rule":    "BUSINESS RULE",
            "join":    "JOIN GUIDANCE",
            "note":    "NOTE",
        }.get(self.kind, "NOTE")
        tag_str = f"  [{', '.join(self.tags)}]" if self.tags else ""
        return f"── {self.title} ({kind_label}){tag_str}\n{self.body}"


# ── Persistence ───────────────────────────────────────────────────────────────

def _path(connection_id: str) -> Path:
    return _DATA_DIR / f"knowledge_{connection_id}.json"


def load_entries(connection_id: str) -> list[KnowledgeEntry]:
    p = _path(connection_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
        return [KnowledgeEntry.from_dict(d) for d in raw]
    except Exception:
        return []


def save_entries(connection_id: str, entries: list[KnowledgeEntry]) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _path(connection_id).write_text(
        json.dumps([e.to_dict() for e in entries], indent=2)
    )


def upsert_entry(connection_id: str, entry: KnowledgeEntry) -> KnowledgeEntry:
    entry.connection_id = connection_id
    if not entry.id:
        entry.id = str(uuid.uuid4())[:8]
    entries = load_entries(connection_id)
    entries = [e for e in entries if e.id != entry.id]
    entries.append(entry)
    save_entries(connection_id, entries)
    _index_entry(entry)
    return entry


def delete_entry(connection_id: str, entry_id: str) -> bool:
    entries = load_entries(connection_id)
    before = len(entries)
    entries = [e for e in entries if e.id != entry_id]
    if len(entries) == before:
        return False
    save_entries(connection_id, entries)
    _delete_from_index(connection_id, entry_id)
    return True


# ── Vector index ──────────────────────────────────────────────────────────────

def _qdrant():
    from aughor.semantic.embedder import get_qdrant_client, VECTOR_SIZE
    client = get_qdrant_client()
    from qdrant_client.models import Distance, VectorParams
    try:
        client.get_collection(_COLLECTION)
    except Exception:
        client.create_collection(
            _COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    return client


def _index_entry(entry: KnowledgeEntry) -> None:
    try:
        from aughor.semantic.embedder import embed
        from qdrant_client.models import PointStruct
        client = _qdrant()
        text = f"{entry.title}\n{entry.body}"
        if entry.tags:
            text += "\n" + " ".join(entry.tags)
        vec = embed(text)
        client.upsert(
            collection_name=_COLLECTION,
            points=[PointStruct(
                id=entry._stable_id(),
                vector=vec,
                payload={
                    "connection_id": entry.connection_id,
                    "entry_id":      entry.id,
                    "title":         entry.title,
                    "body":          entry.body,
                    "kind":          entry.kind,
                    "tags":          entry.tags,
                },
            )],
        )
    except Exception:
        pass   # vector index is best-effort; JSON file is the source of truth


def _delete_from_index(connection_id: str, entry_id: str) -> None:
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client = _qdrant()
        client.delete(
            collection_name=_COLLECTION,
            points_selector=Filter(must=[
                FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
                FieldCondition(key="entry_id",      match=MatchValue(value=entry_id)),
            ]),
        )
    except Exception:
        pass


def rebuild_index(connection_id: str) -> int:
    """Re-index all entries for a connection. Returns count indexed."""
    entries = load_entries(connection_id)
    for e in entries:
        _index_entry(e)
    return len(entries)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve_for_question(question: str, connection_id: str, top_k: int = _TOP_K) -> str:
    """Return a formatted block of relevant knowledge entries for *question*.

    Returns empty string if nothing is relevant or if the knowledge store is
    empty — callers should skip injecting when the result is falsy.
    """
    entries = load_entries(connection_id)
    if not entries:
        return ""

    try:
        from aughor.semantic.embedder import embed
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client = _qdrant()
        vec = embed(question)
        hits = client.search(
            collection_name=_COLLECTION,
            query_vector=vec,
            query_filter=Filter(must=[
                FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
            ]),
            limit=top_k,
            score_threshold=_MIN_SCORE,
        )
        if not hits:
            return ""
        retrieved_ids = {h.payload["entry_id"] for h in hits}
        matched = [e for e in entries if e.id in retrieved_ids]
        if not matched:
            return ""
        lines = ["DOMAIN KNOWLEDGE (use these definitions exactly when writing SQL):"]
        for e in matched:
            lines.append("")
            lines.append(e.render())
        return "\n".join(lines)
    except Exception:
        # Qdrant unavailable — fall back to returning all entries (better than nothing)
        if not entries:
            return ""
        lines = ["DOMAIN KNOWLEDGE (use these definitions exactly when writing SQL):"]
        for e in entries[:top_k]:
            lines.append("")
            lines.append(e.render())
        return "\n".join(lines)
