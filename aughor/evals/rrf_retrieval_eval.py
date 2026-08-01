"""search.rrf — an HONEST, zero-external-budget retrieval-quality eval (experiment queue).

The flag's exit question: does Reciprocal Rank Fusion rank KB retrieval BETTER than the
min-max α-blend on real data? The mechanic is already unit-proven (`test_lexical.py`:
scale-invariance, dispatch, order preservation); this measures the *quality* delta.

**Why this is honest, not a bench-hack:**
- **Real corpus.** The 282 entries under `data/kb/` are the actual production knowledge
  base `hybrid_rerank` reranks over — neutral content nobody wrote for this eval.
- **Definitional labels.** Each query is derived MECHANICALLY from an entry's own fields
  (its title; its `when_to_use` usage lines) and the relevant document is that entry, by
  construction. No hand-picked relevance, no authored queries.
- **Real retrieval, production-exact.** Entries come from the public `load_kb_entries`, so
  each doc's `embed_text` and `payload` are byte-for-byte what production embeds and reranks
  (no private internals, no re-implementation). The local Ollama embedder produces the
  vectors (no external/OpenRouter budget); cosine gives the vector `score` exactly as Qdrant
  would; `payload_text(entry.payload)` feeds BM25 exactly as production does
  (`kb_retriever.py:116`). The only thing that changes between the two arms is the
  `search.rrf` flag.
- **Paired comparison.** The identical top-K candidate pool is reordered by α-blend (flag
  off) and RRF (flag on); the known item's rank is read from each. Whatever the numbers
  say is the answer — a tie or a regression is reported as readily as a win.

Two query regimes, both definitional:
- **title** — the entry's concept name (what a user types); balanced signal.
- **usage** — the entry's `when_to_use` lines joined (natural-language intent);
  semantic-leaning, lower lexical overlap with the title-led embed text.

Run: `uv run python -m aughor.evals.rrf_retrieval_eval` (needs local Ollama +
nomic-embed-text). Reports MRR@10, recall@1, recall@5 for each arm and regime.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass


# ── corpus ────────────────────────────────────────────────────────────────────────

def _kb_dir() -> str:
    import aughor
    return os.path.join(os.path.dirname(os.path.dirname(aughor.__file__)), "data", "kb")


def load_entries() -> list:
    """The production corpus, via the public loader — each KBEntry carries the exact
    ``embed_text`` production sends to the embedder and the ``payload`` it reranks over."""
    from aughor.semantic.kb_loader import load_kb_entries
    return list(load_kb_entries(_kb_dir()))


def embed_text(entry) -> str:
    """Production's exact embed text for this entry (KBEntry.embed_text)."""
    return entry.embed_text


def _usage_query(entry) -> str:
    when = (entry.payload or {}).get("when_to_use", [])
    if isinstance(when, list) and when:
        return " ".join(str(w) for w in when if isinstance(w, str))[:200]
    return ""


def queries_for(entry) -> list[tuple[str, str]]:
    """(regime, query) pairs derived only from the entry's own fields — its concept
    title and its when-to-use lines. Definitional: the relevant doc is this entry."""
    out = []
    title = (entry.title or "").strip()
    if title:
        out.append(("title", title))
    usage = _usage_query(entry).strip()
    if usage and usage.lower() != title.lower():
        out.append(("usage", usage))
    return out


# ── the paired retrieval ────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@dataclass
class ArmMetrics:
    n: int = 0
    mrr: float = 0.0
    r1: float = 0.0
    r5: float = 0.0


def _rank_of(order_ids: list[str], target: str) -> int | None:
    return order_ids.index(target) + 1 if target in order_ids else None


def run(top_k: int = 20, limit_entries: int | None = None) -> dict:
    """Embed the corpus, run every definitional query through both fusion arms over the
    same top-K pool, and return paired MRR/recall. Deterministic given the corpus + model."""
    from aughor.kernel.flags import flag_overrides
    from aughor.semantic.embedder import embed
    from aughor.semantic.lexical import hybrid_rerank, payload_text

    entries = load_entries()
    if limit_entries:
        entries = entries[:limit_entries]
    ids = [e.pattern_id for e in entries]
    payloads = [e.payload for e in entries]
    texts = [embed_text(e) for e in entries]
    doc_vecs = embed(texts)                       # local Ollama; real cosine space

    # all queries up front, batched embed
    q_specs: list[tuple[str, str, str]] = []      # (target_id, regime, query)
    for eid, e in zip(ids, entries):
        for regime, q in queries_for(e):
            q_specs.append((eid, regime, q))
    q_vecs = embed([q for _, _, q in q_specs])

    arms = {("rrf", r): ArmMetrics() for r in ("title", "usage", "ALL")}
    arms.update({("alpha", r): ArmMetrics() for r in ("title", "usage", "ALL")})

    def _accumulate(arm: str, regime: str, rank: int | None):
        for key in ((arm, regime), (arm, "ALL")):
            m = arms[key]
            m.n += 1
            if rank is not None:
                m.mrr += 1.0 / rank
                m.r1 += 1.0 if rank <= 1 else 0.0
                m.r5 += 1.0 if rank <= 5 else 0.0

    for (target, regime, _q), qv in zip(q_specs, q_vecs):
        sims = sorted(
            ({"entry_id": ids[i], "payload": payloads[i], "score": _cosine(qv, doc_vecs[i])}
             for i in range(len(entries))),
            key=lambda h: h["score"], reverse=True)[:top_k]
        q_text = _q
        for arm, on in (("alpha", False), ("rrf", True)):
            with flag_overrides({"search.rrf": on}):
                ordered = hybrid_rerank(q_text, list(sims),
                                        text_of=lambda h: payload_text(h["payload"]))
            _accumulate(arm, regime, _rank_of([h["entry_id"] for h in ordered], target))

    def _fin(m: ArmMetrics) -> dict:
        n = max(1, m.n)
        return {"n": m.n, "mrr": round(m.mrr / n, 4),
                "recall@1": round(m.r1 / n, 4), "recall@5": round(m.r5 / n, 4)}

    return {
        "corpus_entries": len(entries), "queries": len(q_specs), "top_k": top_k,
        "alpha": {r: _fin(arms[("alpha", r)]) for r in ("title", "usage", "ALL")},
        "rrf": {r: _fin(arms[("rrf", r)]) for r in ("title", "usage", "ALL")},
    }


def _verdict(res: dict) -> str:
    a, r = res["alpha"]["ALL"], res["rrf"]["ALL"]
    dm = r["mrr"] - a["mrr"]
    if abs(dm) < 0.005:
        return f"TIE (ΔMRR={dm:+.4f}) — RRF neither helps nor hurts on this corpus"
    return (f"{'RRF WINS' if dm > 0 else 'RRF LOSES'} (ΔMRR={dm:+.4f}, "
            f"alpha={a['mrr']} rrf={r['mrr']})")


if __name__ == "__main__":
    res = run()
    print(json.dumps(res, indent=2))
    print("\nVERDICT:", _verdict(res))
