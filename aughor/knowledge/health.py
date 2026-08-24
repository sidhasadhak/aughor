"""Why the knowledge base answered nothing.

`search_documents` ends `except Exception: return []`. Four different conditions arrive at
that line and leave it identical:

* nothing in the corpus matched the query — fine, and the only one that is;
* no documents are indexed at all;
* the vector store is unreachable or not installed;
* **the embedder is unreachable** — and on this platform that is the common one, because
  embeddings come from a LOCAL Ollama (`semantic/embedder.py` → `localhost:11434`,
  `nomic-embed-text`). It runs on a developer's laptop and does not exist on Vercel, so the
  same code that indexes 92 chunks here indexes nothing there and reports the same empty
  list either way.

Those call for opposite responses — rephrase the question, upload a document, start a
server, configure a backend — and an empty list recommends the first for all four. This
module answers the question the list cannot.

Deliberately a REPORT, not a repair: nothing here starts a server or changes a config. The
value is entirely in a surface being able to say which of the four happened.
"""
from __future__ import annotations

import os

#: The Qdrant/pgvector collection documents live in. Imported rather than re-spelled — a
#: status that probed a different collection than the search does would be worse than none.
from aughor.knowledge.indexer import DOCS_COLLECTION


def embedder_status() -> dict:
    """Can we turn text into a vector right now?

    Probes with a real embedding call, because that is the operation that matters and it is
    the one `available()`-style checks cannot stand in for: `semantic.vector_store.available`
    says the BACKEND is installed and explicitly "says nothing about the server being up".
    The embedder has no such check at all, so this is the only honest answer.
    """
    from aughor.semantic import embedder

    try:
        backend = embedder.embed_backend()
        detail = {"backend": backend, "model": embedder.embed_model(backend),
                  "endpoint": embedder.endpoint()[0]}
    except Exception as exc:
        # Misconfiguration is its own answer, and a more actionable one than a failed
        # call: "no embedding model configured for gemini" names the fix.
        return {"backend": (os.getenv("AUGHOR_EMBED_BACKEND") or "ollama"), "ok": False,
                "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}",
                "why": "the embedding lane is not configured, so nothing can be indexed"}
    try:
        vector = embedder.embed_one("probe")
    except Exception as exc:
        return {**detail, "ok": False,
                "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}",
                "why": ("no embeddings can be produced, so nothing can be indexed and no "
                        "search can run — an empty result here means UNAVAILABLE, not "
                        "'no match'")}
    dim = len(vector)
    # The width the store already holds, when it differs. Indexing refuses on a mismatch;
    # this is how a surface can say WHY before someone tries.
    stored = None
    try:
        from aughor.semantic.vector_store import collection_dim
        stored = collection_dim(DOCS_COLLECTION)
    except Exception:
        stored = None
    out = {**detail, "ok": True, "dim": dim}
    if stored is not None and stored != dim:
        out.update({"ok": False, "stored_dim": stored,
                    "why": (f"the index holds {stored}-dimension vectors and this embedder "
                            f"produces {dim} — the corpus must be re-embedded with one "
                            f"model before anything can be indexed or searched")})
    return out


def store_status() -> dict:
    """Is there a vector store, and does it hold anything?"""
    from aughor.semantic import vector_store

    try:
        backend = vector_store.backend()
        installed = vector_store.available()
    except Exception as exc:
        return {"ok": False, "backend": "unknown",
                "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"}
    if not installed:
        return {"ok": False, "backend": backend, "chunks": 0,
                "why": "the semantic backend is not installed or not configured here"}
    try:
        chunks = vector_store.collection_count(DOCS_COLLECTION)
    except Exception as exc:
        return {"ok": False, "backend": backend,
                "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}",
                "why": "the store is configured but did not answer"}
    return {"ok": True, "backend": backend, "chunks": chunks}


#: Points examined when checking registry↔store agreement. Bounded because this walks the
#: whole collection; a corpus larger than this reports `truncated` rather than a wrong answer.
_DRIFT_SCAN_LIMIT = 20_000


def consistency_status() -> dict:
    """Does the registry agree with the store about what is searchable?

    They are two records of one corpus and nothing reconciles them, so they drift — measured
    on this install, in BOTH directions at once:

    * **orphans** — chunks in the store whose `doc_id` the registry does not list. They are
      returned by search, and they are unreachable by every control: `delete_document` works
      off the registry, and per-agent scoping filters `doc_id in allowed`, which a document
      nobody can list can never be. Searchable, undeletable, unbindable.
    * **under-indexed** — a document the registry says has N chunks where the store holds
      fewer. Those passages simply are not searchable, and nothing says so; the corpus looks
      complete and answers as if the missing part were irrelevant.

    Reported, never repaired. Deleting orphans or re-indexing a short document are both
    destructive-ish acts on someone's corpus, and the point of this function is that the
    person can now SEE the choice.
    """
    from collections import Counter

    from aughor.knowledge.indexer import list_documents
    from aughor.semantic import vector_store

    try:
        registry = {d["doc_id"]: int(d.get("chunk_count") or 0) for d in list_documents()}
    except Exception as exc:
        return {"ok": False, "error": f"registry unreadable: {type(exc).__name__}"}

    seen: Counter = Counter()
    scanned = 0
    try:
        for payload in vector_store.scroll_payloads(DOCS_COLLECTION,
                                                    limit=_DRIFT_SCAN_LIMIT):
            seen[str(payload.get("doc_id") or "")] += 1
            scanned += 1
    except Exception as exc:
        return {"ok": False, "error": f"store unreadable: {type(exc).__name__}"}

    orphans = {doc: n for doc, n in seen.items() if doc not in registry}
    short = {doc: {"registry": n, "store": seen.get(doc, 0)}
             for doc, n in registry.items() if seen.get(doc, 0) != n}
    return {
        "ok": not orphans and not short,
        "truncated": scanned >= _DRIFT_SCAN_LIMIT,
        "orphan_documents": len(orphans),
        "orphan_chunks": sum(orphans.values()),
        "orphans": sorted(orphans),
        "mismatched_documents": short,
        # The number a surface should quote when it says how much is searchable AND
        # controllable: registry-listed chunks that actually exist in the store.
        "listed_chunks_present": sum(min(n, seen.get(doc, 0)) for doc, n in registry.items()),
    }


def knowledge_status() -> dict:
    """The whole plane in one answer: can it index, can it search, does it hold anything.

    `ready` means a search CAN run and has something to search. It is deliberately stricter
    than "no error": a working embedder over an empty collection is healthy and useless, and
    a surface that reports it as ready teaches its reader to distrust the word.
    """
    from aughor.knowledge.indexer import list_documents

    embedder = embedder_status()
    store = store_status()
    drift = consistency_status()
    try:
        documents = len(list_documents())
    except Exception:
        documents = 0

    if not embedder["ok"]:
        reason = "the embedder is unreachable"
    elif not store["ok"]:
        reason = "the vector store is unavailable"
    elif not store.get("chunks"):
        reason = "no documents are indexed"
    else:
        reason = ""

    return {
        "ready": not reason,
        "reason": reason,
        "documents": documents,
        # `chunks` is what the STORE holds, which is the only number that answers "how much
        # can be searched". The registry's own chunk_count sum is a claim, and on this
        # install the two differ.
        "chunks": store.get("chunks", 0),
        "embedder": embedder,
        "store": store,
        "consistency": drift,
    }


def why_empty() -> str:
    """One line a surface can put in front of a person when a search returned nothing.

    Empty string when the plane is healthy — because then an empty result really does mean
    no match, and explaining it would be noise.
    """
    status = knowledge_status()
    if status["ready"]:
        return ""
    detail = status["embedder"].get("why") or status["store"].get("why") or ""
    return f"{status['reason']}{f' — {detail}' if detail else ''}"
