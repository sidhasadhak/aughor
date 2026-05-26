"""
Causal Graph — Sprint 19.

Proposed causal edges are extracted by ADA at the end of each investigation
and stored as proposals keyed by inv_id.  They are only promoted to the
confirmed graph when a recommendation from that investigation is marked
"verified" or "implemented" via the outcome tracker.

Edge weight accumulates (+1 per confirmation, -1 per contradiction) so the
graph degrades gracefully when an edge is later disproved.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

_PROPOSALS_PATH  = Path(__file__).parent.parent.parent / "data" / "causal_proposals.json"
_CONFIRMED_PATH  = Path(__file__).parent.parent.parent / "data" / "causal_graph.json"


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def _edge_id(from_signal: str, to_signal: str) -> str:
    import hashlib
    raw = f"{from_signal.lower().strip()}→{to_signal.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Models ────────────────────────────────────────────────────────────────────

class CausalProposal(BaseModel):
    """A causal link proposed by ADA — awaiting outcome confirmation."""
    from_signal: str        # e.g. "low inventory levels"
    to_signal: str          # e.g. "increased refund rate"
    from_entity: Optional[str] = None   # entity id if identifiable
    to_entity: Optional[str] = None
    confidence: float = 0.5            # ADA's stated confidence 0–1
    inv_id: str
    conn_id: str
    created_at: str = Field(default_factory=_now)


class ConfirmedCausalEdge(BaseModel):
    """A causal link confirmed by at least one verified/implemented outcome."""
    id: str                             # stable: hash of from+to signals
    from_signal: str
    to_signal: str
    from_entity: Optional[str] = None
    to_entity: Optional[str] = None
    weight: int = 1                     # +1 per confirmation, -1 per contradiction
    confirmed_by: list[str] = Field(default_factory=list)   # inv_ids
    conn_id: str
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def _edge_id(from_signal: str, to_signal: str) -> str:
    import hashlib
    raw = f"{from_signal.lower().strip()}→{to_signal.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_proposals() -> dict[str, list[dict]]:
    if not _PROPOSALS_PATH.exists():
        return {}
    with open(_PROPOSALS_PATH) as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _save_proposals(data: dict[str, list[dict]]) -> None:
    _PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PROPOSALS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _load_confirmed() -> list[dict]:
    if not _CONFIRMED_PATH.exists():
        return []
    with open(_CONFIRMED_PATH) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_confirmed(edges: list[dict]) -> None:
    _CONFIRMED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIRMED_PATH, "w") as f:
        json.dump(edges, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def save_proposals(inv_id: str, proposals: list[CausalProposal]) -> None:
    """Store ADA's proposed causal links for an investigation."""
    data = _load_proposals()
    data[inv_id] = [p.model_dump() for p in proposals]
    _save_proposals(data)


def load_proposals(inv_id: str) -> list[CausalProposal]:
    return [CausalProposal(**p) for p in _load_proposals().get(inv_id, [])]


def promote_on_outcome(inv_id: str, contradicted: bool = False) -> int:
    """
    Promote (or weaken) causal proposals from inv_id based on an outcome.

    contradicted=False (verified/implemented) → weight +1 or create edge
    contradicted=True  (rejected)             → weight -1, remove at 0

    Returns number of edges affected.
    """
    proposals = load_proposals(inv_id)
    if not proposals:
        return 0

    confirmed = _load_confirmed()
    edge_map: dict[str, dict] = {e["id"]: e for e in confirmed}

    affected = 0
    for proposal in proposals:
        eid = _edge_id(proposal.from_signal, proposal.to_signal)
        if contradicted:
            if eid in edge_map:
                edge_map[eid]["weight"] -= 1
                edge_map[eid]["updated_at"] = _now()
                affected += 1
        else:
            if eid in edge_map:
                # Reinforce existing edge
                existing = edge_map[eid]
                existing["weight"] = existing.get("weight", 1) + 1
                existing["updated_at"] = _now()
                if inv_id not in existing.get("confirmed_by", []):
                    existing.setdefault("confirmed_by", []).append(inv_id)
            else:
                # Promote new edge
                edge = ConfirmedCausalEdge(
                    id=eid,
                    from_signal=proposal.from_signal,
                    to_signal=proposal.to_signal,
                    from_entity=proposal.from_entity,
                    to_entity=proposal.to_entity,
                    weight=1,
                    confirmed_by=[inv_id],
                    conn_id=proposal.conn_id,
                )
                edge_map[eid] = edge.model_dump()
            affected += 1

    # Prune edges with weight <= 0
    surviving = [e for e in edge_map.values() if e.get("weight", 1) > 0]
    _save_confirmed(surviving)
    return affected


def load_causal_graph(conn_id: Optional[str] = None) -> list[ConfirmedCausalEdge]:
    """Load all confirmed causal edges, optionally filtered by connection."""
    edges = _load_confirmed()
    if conn_id:
        edges = [e for e in edges if e.get("conn_id") == conn_id]
    return [ConfirmedCausalEdge(**e) for e in edges]


def backward_traverse(
    target_signal: str,
    conn_id: Optional[str] = None,
    depth: int = 3,
) -> list[ConfirmedCausalEdge]:
    """
    Walk the causal graph backwards from target_signal to find upstream causes.
    Returns edges in order from most-proximate to most-distal.
    """
    edges = load_causal_graph(conn_id)
    target_lower = target_signal.lower()

    found: list[ConfirmedCausalEdge] = []
    visited: set[str] = set()
    frontier = {target_lower}

    for _ in range(depth):
        next_frontier: set[str] = set()
        for edge in edges:
            if edge.to_signal.lower() in frontier and edge.id not in visited:
                found.append(edge)
                visited.add(edge.id)
                next_frontier.add(edge.from_signal.lower())
        if not next_frontier:
            break
        frontier = next_frontier

    return found


def build_causal_context_section(question: str, conn_id: Optional[str] = None) -> str:
    """
    Build a prompt section with upstream causal context for a question.
    Used by the playbook retriever to enrich investigation context.
    """
    edges = backward_traverse(question, conn_id=conn_id, depth=2)
    if not edges:
        return ""
    lines = ["KNOWN CAUSAL PATTERNS (from prior verified investigations):"]
    for e in edges[:6]:
        weight_note = f" (confirmed {e.weight}×)" if e.weight > 1 else ""
        lines.append(f"  • {e.from_signal} → {e.to_signal}{weight_note}")
    return "\n".join(lines) + "\n"
