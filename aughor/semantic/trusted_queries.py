"""Trusted query templates — curated, data-team-reviewed SQL patterns.

The Databricks-Genie / Foundry "trusted assets" idea: a small store of KNOWN-CORRECT
queries for a connection. When a user's question matches one, the verified pattern
is injected AUTHORITATIVELY into the prompt ("reuse this exact join/aggregation
structure"), and the answer can be marked Verified. This bypasses model-reasoning
gaps that prompt rules can't fix — most importantly multi-fact FAN-OUT (the model
resists the "pre-aggregate then join" rule during generation but adapts a concrete
verified example correctly).

Distinct from `prior_analyses.search_sql_examples` (auto-collected soft few-shots):
these are deliberately curated, authoritative, and provenance-marked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

_PATH = Path(__file__).parent.parent.parent / "data" / "trusted_queries.json"

# Generic words that shouldn't drive matching.
_STOP = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by", "per",
    "each", "what", "which", "how", "many", "is", "are", "was", "were", "do",
    "does", "show", "list", "give", "me", "their", "its", "with", "that", "this",
})


class TrustedQuery(BaseModel):
    id: str
    connection_id: str
    question: str                       # canonical question / intent it answers
    sql: str                            # verified-correct DuckDB SQL
    tables: list[str] = Field(default_factory=list)
    note: str = ""                      # what pattern/pitfall it demonstrates
    tags: list[str] = Field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if t not in _STOP and len(t) > 2}


def _load_raw() -> list[dict]:
    if not _PATH.exists():
        return []
    try:
        return json.loads(_PATH.read_text()) or []
    except Exception:
        return []


def list_trusted(connection_id: str = "") -> list[TrustedQuery]:
    out = []
    for d in _load_raw():
        try:
            tq = TrustedQuery(**d)
        except Exception:
            continue
        if not connection_id or tq.connection_id == connection_id:
            out.append(tq)
    return out


def save_trusted(tq: TrustedQuery) -> None:
    raw = [d for d in _load_raw() if d.get("id") != tq.id]
    raw.append(tq.model_dump())
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    tmp.replace(_PATH)


def delete_trusted(tq_id: str) -> bool:
    raw = _load_raw()
    kept = [d for d in raw if d.get("id") != tq_id]
    if len(kept) == len(raw):
        return False
    _PATH.write_text(json.dumps(kept, indent=2))
    return True


def retrieve_trusted(question: str, connection_id: str, top_k: int = 2,
                     min_score: float = 0.18) -> list[tuple[TrustedQuery, float]]:
    """Top trusted queries whose question overlaps the user's, by token-overlap
    score (intersection / query-token count). Conservative threshold so an
    unrelated question injects nothing."""
    qtok = _tokens(question)
    if not qtok:
        return []
    scored = []
    for tq in list_trusted(connection_id):
        ttok = _tokens(tq.question) | {t for tag in tq.tags for t in _tokens(tag)}
        if not ttok:
            continue
        score = len(qtok & ttok) / len(qtok)
        if score >= min_score:
            scored.append((tq, round(score, 3)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def build_trusted_block(matches: list[tuple[TrustedQuery, float]]) -> str:
    """Authoritative prompt section. Stronger than soft examples: the model is
    told these are verified and to reuse the exact structure."""
    if not matches:
        return ""
    lines = [
        "VERIFIED QUERY PATTERNS (data-team reviewed, KNOWN-CORRECT for this database). "
        "When the user's question matches one of these, REUSE its exact join and aggregation "
        "structure — adapt only the filters, columns, or grouping the question actually changes. "
        "These patterns avoid common errors (fan-out row multiplication, wrong grain):",
    ]
    for i, (tq, _score) in enumerate(matches, 1):
        lines.append(f"\n-- Verified pattern {i}" + (f" — {tq.note}" if tq.note else ""))
        lines.append(f"Q: {tq.question}\nSQL:\n{tq.sql.strip()}")
    lines.append("")
    return "\n".join(lines)
