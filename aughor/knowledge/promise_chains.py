"""HB-3 — the Briefing's chain leg: a promise's breach rate before and after, with the
chain between them.

Deterministic and model-free, like `metric_moves`: every number here was RECORDED — the
breach rate the links store snapshotted when a ticket/thread was filed on the promise,
the outcome a person wrote at close, and the stamped rate now. Shaped exactly like an
explorer finding so it flows through triage and into the narrative citable, under its
own "Promises" domain. On a frozen dataset before and after are honestly equal; the
sentence then says the rate is unchanged, because it is.
"""
from __future__ import annotations

from aughor.kernel.errors import tolerate


def promise_chain_findings(conn_id: str) -> list[dict]:
    """One synthetic finding per promise that has filed links on this connection.
    Empty on any trouble — the Briefing must not fail for want of a chain."""
    try:
        from aughor.hub.links import list_links, stamped_measures
        links = [ln for ln in list_links(limit=200)
                 if str(ln.get("object_ref", "")).startswith("promise:")]
    except Exception as exc:
        tolerate(exc, "promise chains unavailable — the Briefing goes on without them",
                 counter="brief.promise_chains")
        return []
    if not links:
        return []

    by_ref: dict[str, list[dict]] = {}
    for ln in links:
        by_ref.setdefault(ln["object_ref"], []).append(ln)

    out: list[dict] = []
    for ref, rows in sorted(by_ref.items()):
        now = stamped_measures(ref)
        # The promise's home connection comes from the stamped snapshot — filing's,
        # else the current read. A promise this connection did not declare is skipped.
        home = (now.get("connection_id")
                or next((r["metrics_at_filing"].get("connection_id")
                         for r in rows if r.get("metrics_at_filing")), ""))
        if home and home != conn_id:
            continue
        rows.sort(key=lambda r: str(r.get("ts", "")))
        first = rows[0]
        at_filing = (first.get("metrics_at_filing") or {}).get("breach_rate")
        rate_now = now.get("breach_rate")
        closed = [r for r in rows if r.get("status") == "closed"]
        chain = " → ".join(f"{r['kind']} {r.get('ref') or r['id']}" for r in rows[:4])

        parts = [f"The {ref} promise has {len(rows)} filed "
                 f"{'link' if len(rows) == 1 else 'links'} ({chain})."]
        if at_filing is not None and rate_now is not None:
            pct = lambda v: f"{float(v) * 100:.2f}%"  # noqa: E731
            if at_filing == rate_now:
                parts.append(f"Breach rate is unchanged at {pct(rate_now)} since filing.")
            else:
                parts.append(f"Breach rate moved from {pct(at_filing)} to {pct(rate_now)} "
                             f"since filing.")
        for r in closed[:2]:
            outcome = r.get("outcome") or "closed"
            recovered = r.get("number_recovered") or ""
            parts.append(f"{r['kind']} {r.get('ref') or r['id']} closed: {outcome}"
                         + (f" ({recovered} recovered)" if recovered else "") + ".")
        if not closed:
            parts.append("No outcome recorded yet.")

        slug = ref.split(":", 1)[1].replace(".", "_")[:40]
        out.append({
            "id": f"promise-chain::{slug}",
            "domain": "Promises",
            "angle": "Outcome",
            "finding": " ".join(parts),
            "sql": "",
            # Recorded facts (filed refs, a person's close, stamped rates) — high trust.
            "confidence": 0.9,
            "novelty": 3,
            "promise_chain": True,
        })
    return out
