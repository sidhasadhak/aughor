"""A pack's measured record — the listing IS the record (the 2027 study §Q; phase 7, P7-3).

A pack is listed with what the installs that bound it found: how often its claims held when measured
against real data (the pack writer's hypotheses in the Record, by state), how its package measured on
its public dataset (gate 4's receipts), and the journal of who promoted or demoted it. A pack whose
claims keep failing on real installs is demoted by the same receipt that promoted it — the record —
and the demotion is a person's act with the record cited, or refused when the record does not say so
(a person may still demote with `force` and a reason, which the journal carries).
"""
from __future__ import annotations

from typing import Any, Optional

#: A demotion is due when at least this many of a pack's claims were measured on installs …
DEMOTION_MIN_MEASURED = 10
#: … and this share of the measured ones were refuted by the data.
DEMOTION_REFUTED_SHARE = 0.5


def claims_record(pack_id: str) -> dict[str, Any]:
    """What the Record holds of the pack's claims across every connection: counts by state and kind,
    the share that held of those the data could speak to, and how many connections measured it."""
    from aughor.record import claims as C
    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    conns: set[str] = set()
    for c in C.list_claims(kind="hypothesis", limit=10000):
        if c.extra.get("writer") != "pack" or c.extra.get("pack") != pack_id:
            continue
        state = c.state or "open"
        by_state[state] = by_state.get(state, 0) + 1
        k = str(c.extra.get("claim_kind") or "")
        by_kind[k] = by_kind.get(k, 0) + 1
        if c.about.kind == "connection" and c.about.key:
            conns.add(c.about.key)
    supported, refuted = by_state.get("supported", 0), by_state.get("refuted", 0)
    measured = supported + refuted
    return {"by_state": by_state, "by_kind": by_kind, "supported": supported, "refuted": refuted, "open": by_state.get("open", 0),
            "measured": measured, "held_share": round(supported / measured, 3) if measured else None, "connections": len(conns),
            "note": ("no install has measured this pack's claims yet" if not by_state else
                     "open: the data could not speak; supported and refuted: it did")}


def gate_receipts(pack_id: str) -> list[dict[str, Any]]:
    """Gate 4's receipts on the package's named public datasets."""
    out = []
    try:
        from aughor.packs.gate4 import read_receipt
        from aughor.packs.ontology_map import load_pack_by_id
        pack = load_pack_by_id(pack_id)
        if pack is None:
            return out
        for ds in pack.datasets:
            r = read_receipt(pack, ds.id)
            if not r:
                out.append({"dataset": ds.id, "measured": False})
                continue
            metrics = list(r.get("metrics") or [])
            out.append({"dataset": ds.id, "measured": True, "measured_at": r.get("measured_at", ""),
                        "metrics": len(metrics), "in_range": sum(1 for m in metrics if m.get("in_range")),
                        "errors": sum(1 for m in metrics if m.get("error"))})
    except Exception as exc:  # noqa: BLE001 — an unreadable receipt is said, never a crash
        from aughor.kernel.errors import tolerate
        tolerate(exc, "gate 4 receipts could not be read", counter="packs.record.receipts")
    return out


def status_journal(pack_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Who moved the pack between draft, active and deprecated, and when."""
    try:
        from aughor.kernel.ledger import Ledger
        rows = Ledger.default().events(kind="pack.status_changed", limit=2000)
        rows += Ledger.default().events(kind="pack.demoted", limit=500)
        rows += Ledger.default().events(kind="pack.uploaded", limit=500)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the pack's journal could not be read", counter="packs.record.journal")
        return []
    mine = [r for r in rows if str((r.get("payload") or {}).get("pack_id") or "") == pack_id]
    mine.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return [{"at": r.get("at"), "kind": r.get("kind"), **{k: v for k, v in (r.get("payload") or {}).items() if k != "pack_id"}}
            for r in mine[:limit]]


def demotion_verdict(claims: dict[str, Any]) -> dict[str, Any]:
    measured = int(claims.get("measured") or 0)
    refuted = int(claims.get("refuted") or 0)
    if measured < DEMOTION_MIN_MEASURED:
        return {"due": False, "why": f"{measured} of the pack's claims measured on installs; a demotion is read from {DEMOTION_MIN_MEASURED} or more"}
    share = refuted / measured
    if share >= DEMOTION_REFUTED_SHARE:
        return {"due": True, "why": f"{refuted} of {measured} measured claims were refuted by the data ({share:.0%}); the bar is {DEMOTION_REFUTED_SHARE:.0%}"}
    return {"due": False, "why": f"{refuted} of {measured} measured claims were refuted ({share:.0%}); below the {DEMOTION_REFUTED_SHARE:.0%} bar"}


def measured_record(pack_id: str) -> dict[str, Any]:
    """The record a pack is listed with."""
    from aughor.packs.ontology_map import load_pack_by_id
    pack = load_pack_by_id(pack_id)
    claims = claims_record(pack_id)
    return {"pack": pack_id, "status": pack.manifest.status if pack else "unloadable", "layer": pack.manifest.layer if pack else "",
            "source": pack.manifest.source if pack else "", "claims": claims, "gates": gate_receipts(pack_id),
            "journal": status_journal(pack_id), "demotion": demotion_verdict(claims)}


def demote(pack_id: str, *, by: str, why: str = "", force: bool = False) -> dict[str, Any]:
    """Demote a pack on its measured record — the receipt that promoted it. Refused when the record
    does not say so, unless a person forces it with a reason; either way the journal carries the
    record. Demotion is never gated otherwise: taking something out of service needs no test."""
    if not (by or "").strip():
        raise ValueError("a demotion is a person's act, named")
    record = measured_record(pack_id)
    verdict = record["demotion"]
    if not verdict["due"]:
        if not force:
            raise ValueError(f"the record does not call for a demotion: {verdict['why']}. A person may force it with a reason.")
        if not (why or "").strip():
            raise ValueError("a forced demotion says why")
    from aughor.packs.promote import set_status
    pack = set_status(pack_id, "deprecated", actor=by)
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("pack.demoted", {"pack_id": pack_id, "by": by, "record": record["claims"], "why": (why or verdict["why"])[:400],
                                               "forced": force and not verdict["due"]})
    except Exception:  # noqa: BLE001
        pass
    return {**measured_record(pack_id), "status": pack.manifest.status, "demoted": True, "why": why or verdict["why"]}


def listing() -> list[dict[str, Any]]:
    """Every pack with its record — the listing a third party's pack is judged in."""
    from aughor.packs.ontology_map import load_pack_by_id
    from aughor.packs.roots import all_pack_ids
    out = []
    for pid in all_pack_ids():
        pack = load_pack_by_id(pid)
        rec = measured_record(pid)
        out.append({"id": pid, "name": pack.manifest.name if pack else pid, "status": rec["status"], "layer": rec["layer"],
                    "source": rec["source"], "description": pack.manifest.description if pack else "",
                    "claims": {k: rec["claims"][k] for k in ("measured", "supported", "refuted", "open", "held_share", "connections")},
                    "gates": [{"dataset": g["dataset"], "measured": g["measured"], "in_range": g.get("in_range"), "metrics": g.get("metrics")} for g in rec["gates"]],
                    "demotion_due": rec["demotion"]["due"]})
    return out


def record_summary(pack_id: str) -> Optional[dict[str, Any]]:
    try:
        return measured_record(pack_id)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a pack's record could not be read", counter="packs.record")
        return None
