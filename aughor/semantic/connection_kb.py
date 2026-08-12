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


def purge_connection(connection_id: str) -> int:
    """Delete this connection's entire knowledge store — the JSON file (source of
    truth) and all its vector points (catalog-delete cascade). Returns 1 if a JSON
    file was removed, else 0. The vector purge is best-effort."""
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        from aughor.semantic.vector_store import delete_by_filter
        delete_by_filter(_COLLECTION, Filter(must=[
            FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
        ]))
    except Exception as e:
        # Vector index is best-effort; the JSON file is the source of truth.
        from aughor.kernel.errors import tolerate
        tolerate(e, "connection_kb purge: vector delete", counter="connection_kb.purge.vector")
    p = _path(connection_id)
    if p.exists():
        p.unlink()
        return 1
    return 0


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
    _invalidate_linker_hints(connection_id)
    return entry


def delete_entry(connection_id: str, entry_id: str) -> bool:
    entries = load_entries(connection_id)
    before = len(entries)
    entries = [e for e in entries if e.id != entry_id]
    if len(entries) == before:
        return False
    save_entries(connection_id, entries)
    _delete_from_index(connection_id, entry_id)
    _invalidate_linker_hints(connection_id)
    return True


def _invalidate_linker_hints(connection_id: str) -> None:
    """Refresh the schema-linker's per-connection hint cache after a KB edit."""
    try:
        from aughor.tools.schema_linker import invalidate_hints
        invalidate_hints(connection_id)
    except Exception:
        pass


# ── Vector index ──────────────────────────────────────────────────────────────
# Repointed at aughor.semantic.vector_store (the working Qdrant wrapper). The old
# path imported get_qdrant_client / VECTOR_SIZE from embedder.py — neither symbol
# exists there — so every index and search raised ImportError, was swallowed by a
# bare `except: pass`, and retrieval silently degraded to an UNRANKED entries[:k].
# Wave C2 fix: use the public wrapper (same substrate the context graph uses), count
# failures through tolerate, and make the fallback a RANKED lexical rank.

def _entry_payload(entry: KnowledgeEntry) -> dict:
    return {
        "connection_id": entry.connection_id,
        "entry_id":      entry.id,
        "title":         entry.title,
        "body":          entry.body,
        "kind":          entry.kind,
        "tags":          entry.tags,
    }


def _index_entry(entry: KnowledgeEntry) -> None:
    try:
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import ensure_collection, upsert
        ensure_collection(_COLLECTION)
        text = f"{entry.title}\n{entry.body}"
        if entry.tags:
            text += "\n" + " ".join(entry.tags)
        upsert(_COLLECTION, [{
            "id": f"{entry.connection_id}:{entry.id}",
            "vector": embed_one(text),
            "payload": _entry_payload(entry),
        }])
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection-KB vector index is best-effort; the JSON file is the "
                      "source of truth", counter="connection_kb.index")


def _delete_from_index(connection_id: str, entry_id: str) -> None:
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        from aughor.semantic.vector_store import delete_by_filter
        delete_by_filter(_COLLECTION, Filter(must=[
            FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
            FieldCondition(key="entry_id",      match=MatchValue(value=entry_id)),
        ]))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection-KB vector delete is best-effort", counter="connection_kb.delete")


def rebuild_index(connection_id: str) -> int:
    """Re-index all entries for a connection. Returns count indexed."""
    entries = load_entries(connection_id)
    for e in entries:
        _index_entry(e)
    return len(entries)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _lexical_rank(question: str, entries: list, top_k: int) -> list:
    """Deterministic token-overlap rank — the floor when Qdrant is unreachable. The
    old fallback returned entries[:top_k] (arbitrary order); this at least RANKS by
    relevance, so an unavailable vector store degrades to worse recall, never to
    unranked noise (the connection-KB analogue of the context-graph search floor)."""
    import re
    q = {t for t in re.findall(r"[a-z0-9_]+", (question or "").lower()) if len(t) > 2}
    if not q:
        return entries[:top_k]
    scored = [(len({t for t in re.findall(r"[a-z0-9_]+", e.render().lower()) if len(t) > 2} & q), e)
              for e in entries]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _s, e in scored[:top_k]]


#: The PROMPT header — an instruction addressed to a model. Reader-facing renders
#: must never carry it (see retrieve_for_reader).
_PROMPT_HEADER = "DOMAIN KNOWLEDGE (use these definitions exactly when writing SQL):"


def _render_block(entries: list, header: str | None = _PROMPT_HEADER) -> str:
    if not entries:
        return ""
    lines = [header] if header else []
    for e in entries:
        if lines:
            lines.append("")
        lines.append(e.render())
    return "\n".join(lines)


def retrieve_for_reader(question: str, connection_id: str, top_k: int = _TOP_K) -> str:
    """The same relevant entries rendered as part of an ANSWER — no instruction header.

    ``retrieve_for_question`` writes a prompt block whose first line tells a MODEL what
    to do with the definitions; the definitional chat path once appended that block
    verbatim to the user's answer. A reader gets the entries' own prose and nothing
    addressed to someone else."""
    return _render_block(_relevant_entries(question, connection_id, top_k), header=None)


def retrieve_for_question(question: str, connection_id: str, top_k: int = _TOP_K) -> str:
    """Return a formatted block of relevant knowledge entries for *question*,
    headed for PROMPT injection.

    Returns empty string if nothing is relevant or if the knowledge store is
    empty — callers should skip injecting when the result is falsy.
    """
    return _render_block(_relevant_entries(question, connection_id, top_k))


def _relevant_entries(question: str, connection_id: str, top_k: int = _TOP_K) -> list:
    """The ranked relevant entries themselves — retrieval without a register."""
    entries = load_entries(connection_id)
    if not entries:
        return []
    try:
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.lexical import hybrid_rerank
        from aughor.semantic.vector_store import collection_count, search
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        if collection_count(_COLLECTION) == 0:
            return _lexical_rank(question, entries, top_k)
        # embed_one → a FLAT 768-vec (embed() nests [[…]] for a single string, which
        # Qdrant rejects — the original R7 note).
        vec = embed_one(question)
        hits = search(_COLLECTION, vec, top_k=top_k * 3, query_filter=Filter(must=[
            FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
        ]))
        by_id = {e.id: e for e in entries}
        cands = [{"score": h.get("score", 0.0), "entry_id": (h.get("payload") or {}).get("entry_id")}
                 for h in hits
                 if h.get("score", 0.0) >= _MIN_SCORE and (h.get("payload") or {}).get("entry_id") in by_id]
        # Vector search ran and nothing cleared the threshold ⇒ inject nothing (conservative,
        # as before) — NOT the lexical fallback, which is only for when there is no vector
        # signal at all (Qdrant down / never indexed).
        if not cands:
            return []
        # HYBRID rerank: blend vector score with BM25 over each entry's text so an exact
        # metric/column name surfaces; preserve the reranked order, then take top_k.
        cands = hybrid_rerank(question, cands, text_of=lambda c: by_id[c["entry_id"]].render())
        return [by_id[c["entry_id"]] for c in cands][:top_k]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection-KB vector retrieval is best-effort; ranked lexical "
                      "fallback used (never unranked)", counter="connection_kb.retrieve")
        return _lexical_rank(question, entries, top_k)
