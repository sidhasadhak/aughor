"""CB-4 (2026-09-22) — remember a rejected duplicate.

`dedup.detect_duplicate_entities` suggests near-duplicate business objects (Customer and Client)
from embedding similarity, recomputed on every read. Nothing recorded a person's "no, these are
different", so a pair someone had already rejected came back on every visit. The ontology already
does this right twice — a dismissed recommendation never returns (`recommendations.py`), a proposal
the explorer withdrew is not made again (`explorer._withdrawn`) — so this is that pattern, repeated.

A rejection is a person's decision about the ontology, kept with its reason and who made it, in the
same tree as dismissed recommendations (`recommendations_root()/{conn}/{schema}/rejected_duplicates.yaml`),
keyed by the UNORDERED pair. Reading applies it: a suggested cluster whose every pair was rejected
is hidden (and counted); a larger cluster with some pairs rejected stays, annotated, because the
other pairs were never judged. A rejection can be reconsidered. Detection itself stays pure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

FILE_NAME = "rejected_duplicates.yaml"


def pair_key(a: str, b: str) -> tuple[str, str]:
    """The unordered pair, as a sorted tuple. (Client, Customer) and (Customer, Client) are one."""
    x, y = str(a or "").strip(), str(b or "").strip()
    return (x, y) if x <= y else (y, x)


def _path(conn: str, schema: str) -> Path:
    from aughor.ontology.recommendations import recommendations_root, safe_name
    return recommendations_root() / safe_name(conn) / safe_name(schema or "default") / FILE_NAME


def _load(conn: str, schema: str) -> list[dict]:
    p = _path(conn, schema)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text()) or []
    except Exception as exc:  # noqa: BLE001 — an unreadable file is an empty ledger with a trace
        from aughor.kernel.errors import tolerate
        tolerate(exc, "rejected-duplicates file could not be read; treated as empty", counter="dedup.rejections")
        return []
    return [d for d in data if isinstance(d, dict) and isinstance(d.get("pair"), list) and len(d["pair"]) == 2]


def _save(conn: str, schema: str, rows: list[dict]) -> None:
    p = _path(conn, schema)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True))


def rejected_pairs(conn: str, schema: str) -> dict[tuple[str, str], dict]:
    """Every rejected pair on this scope, keyed by the unordered pair."""
    out: dict[tuple[str, str], dict] = {}
    for d in _load(conn, schema):
        k = pair_key(d["pair"][0], d["pair"][1])
        out[k] = {**d, "pair": list(k)}
    return out


def reject(conn: str, schema: str, entity_ids: list[str], *, reason: str = "", rejected_by: str = "") -> list[dict]:
    """Record "these are different" for every pair among ``entity_ids`` (two or more). Re-rejecting a
    pair replaces its reason. Returns the rows written. Raises ``ValueError`` for fewer than two ids."""
    ids = sorted({str(i).strip() for i in entity_ids if str(i or "").strip()})
    if len(ids) < 2:
        raise ValueError("two or more entity ids are required")
    rows = _load(conn, schema)
    now = datetime.now(timezone.utc).isoformat()
    written = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            k = pair_key(a, b)
            row = {"pair": list(k), "reason": " ".join((reason or "").split()), "rejected_by": rejected_by or "",
                   "rejected_at": now}
            rows = [r for r in rows if pair_key(r["pair"][0], r["pair"][1]) != k]
            rows.append(row)
            written.append(row)
    _save(conn, schema, rows)
    return written


def reconsider(conn: str, schema: str, a: str, b: str) -> bool:
    """Take a rejection back. True when one was there."""
    k = pair_key(a, b)
    rows = _load(conn, schema)
    kept = [r for r in rows if pair_key(r["pair"][0], r["pair"][1]) != k]
    if len(kept) == len(rows):
        return False
    _save(conn, schema, kept)
    return True


def apply_rejections(clusters: list[dict], rejected: dict[tuple[str, str], dict]) -> tuple[list[dict], int]:
    """``(clusters_to_show, hidden)``. A cluster whose every pair was rejected is hidden; one with some
    pairs rejected is kept with ``rejected_pairs`` on it — the other pairs were never judged."""
    if not rejected:
        return list(clusters), 0
    shown, hidden = [], 0
    for c in clusters:
        ids = [str(e.get("id") or "") for e in (c.get("entities") or [])]
        pairs = [pair_key(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
        struck = [p for p in pairs if p in rejected]
        if pairs and len(struck) == len(pairs):
            hidden += 1
            continue
        out = dict(c)
        if struck:
            out["rejected_pairs"] = [{"pair": list(p), "reason": rejected[p].get("reason", "")} for p in struck]
        shown.append(out)
    return shown, hidden


def detect_with_decisions(graph, conn: str, schema: str, *, threshold: Optional[float] = None) -> dict:
    """What the door returns: the detector's suggestions with this scope's rejections applied."""
    from aughor.ontology.dedup import DEFAULT_THRESHOLD, detect_duplicate_entities
    clusters = detect_duplicate_entities(graph, threshold=threshold if threshold is not None else DEFAULT_THRESHOLD)
    rej = rejected_pairs(conn, schema)
    shown, hidden = apply_rejections(clusters, rej)
    return {"clusters": shown, "hidden": hidden, "rejected": list(rej.values())}
